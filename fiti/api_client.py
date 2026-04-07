import os
import json
import socket
import urllib.request
import urllib.error
from typing import List

GEMINI_MODEL = "gemini-2.5-flash"
ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
_TIMEOUT = 30
_MAX_ERROR_BODY = 500


class APIClient:
    def __init__(self):
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY")

        if not self.anthropic_api_key and not self.gemini_api_key:
            raise RuntimeError("API Key required. Set GEMINI_API_KEY or ANTHROPIC_API_KEY.")

    # ── Simple single-turn calls ───────────────────────────────────────────

    def call_gemini(self, prompt: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}]
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "x-goog-api-key": self.gemini_api_key,
        }, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            preview = e.read().decode(errors="replace")[:_MAX_ERROR_BODY]
            raise RuntimeError(f"Gemini API error: {preview}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error reaching Gemini API: {e.reason}")
        except socket.timeout:
            raise RuntimeError("Gemini API request timed out.")
        except json.JSONDecodeError:
            raise RuntimeError("Gemini API returned malformed JSON.")

        try:
            return body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected Gemini API response structure: {e}")

    def call_anthropic(self, prompt: str, max_tokens: int = 1024) -> str:
        url = "https://api.anthropic.com/v1/messages"
        payload = json.dumps({
            "model": ANTHROPIC_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={
            "x-api-key": self.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            preview = e.read().decode(errors="replace")[:_MAX_ERROR_BODY]
            raise RuntimeError(f"Anthropic API error: {preview}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error reaching Anthropic API: {e.reason}")
        except socket.timeout:
            raise RuntimeError("Anthropic API request timed out.")
        except json.JSONDecodeError:
            raise RuntimeError("Anthropic API returned malformed JSON.")

        try:
            return body["content"][0]["text"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected Anthropic API response structure: {e}")

    def call(self, prompt: str, max_tokens: int = 1024) -> str:
        """Call whichever API is configured, preferring Gemini."""
        if self.gemini_api_key:
            return self.call_gemini(prompt)
        return self.call_anthropic(prompt, max_tokens=max_tokens)

    # ── Multi-turn tool-calling ────────────────────────────────────────────

    def call_with_tools(
        self,
        messages: list,
        tools: list,
        system: str = "",
        max_tokens: int = 4096,
    ) -> dict:
        """
        Send messages with tool definitions. Returns:
        {
            "stop_reason": "end_turn" | "tool_use",
            "text": str,
            "tool_calls": [{"name": str, "id": str, "input": dict}],
            "raw_messages": list,   # updated messages list to continue the loop
        }
        """
        if self.gemini_api_key:
            return self._call_with_tools_gemini(messages, tools, system, max_tokens)
        return self._call_with_tools_anthropic(messages, tools, system, max_tokens)

    # ── Anthropic tool calling ─────────────────────────────────────────────

    def _call_with_tools_anthropic(self, messages, tools, system, max_tokens):
        anthropic_tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["parameters"],
            }
            for t in tools
        ]
        payload_dict = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": max_tokens,
            "tools": anthropic_tools,
            "messages": messages,
        }
        if system:
            payload_dict["system"] = system

        payload = json.dumps(payload_dict).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": self.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            preview = e.read().decode(errors="replace")[:_MAX_ERROR_BODY]
            raise RuntimeError(f"Anthropic API error: {preview}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error reaching Anthropic API: {e.reason}")
        except socket.timeout:
            raise RuntimeError("Anthropic API request timed out.")
        except json.JSONDecodeError:
            raise RuntimeError("Anthropic API returned malformed JSON.")

        stop_reason = body.get("stop_reason", "end_turn")
        content_blocks = body.get("content", [])

        text = " ".join(b["text"] for b in content_blocks if b.get("type") == "text")
        tool_calls = [
            {"name": b["name"], "id": b["id"], "input": b["input"]}
            for b in content_blocks if b.get("type") == "tool_use"
        ]

        # Build updated messages for next turn
        raw_messages = list(messages) + [{"role": "assistant", "content": content_blocks}]
        if tool_calls:
            raw_messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": "",   # caller fills this in via inject_tool_results
                    }
                    for tc in tool_calls
                ],
            })

        return {
            "stop_reason": "tool_use" if stop_reason == "tool_use" else "end_turn",
            "text": text.strip(),
            "tool_calls": tool_calls,
            "raw_messages": raw_messages,
        }

    def inject_tool_results_anthropic(self, raw_messages: list, tool_calls: list, results: List[str]) -> list:
        """Fill in tool_result content in the last user message."""
        updated = list(raw_messages)
        last = updated[-1]
        result_map = {tc["id"]: r for tc, r in zip(tool_calls, results)}
        updated[-1] = {
            "role": "user",
            "content": [
                {**block, "content": result_map.get(block.get("tool_use_id", ""), "")}
                for block in last["content"]
            ],
        }
        return updated

    # ── Gemini tool calling ────────────────────────────────────────────────

    def _call_with_tools_gemini(self, messages, tools, system, max_tokens):
        function_declarations = [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
            for t in tools
        ]

        # Translate messages → Gemini contents format
        contents = []
        system_injected = False
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            content = msg["content"]

            if isinstance(content, str):
                text = content
                if role == "user" and not system_injected and system:
                    text = f"{system}\n\n{text}"
                    system_injected = True
                contents.append({"role": role, "parts": [{"text": text}]})
            elif isinstance(content, list):
                # Multi-part content (tool results or tool calls)
                parts = []
                for block in content:
                    if block.get("type") == "tool_result":
                        parts.append({
                            "functionResponse": {
                                "name": block.get("name", ""),
                                "response": {"result": block.get("content", "")},
                            }
                        })
                    elif block.get("type") == "tool_use":
                        parts.append({
                            "functionCall": {
                                "name": block["name"],
                                "args": block.get("input", {}),
                            }
                        })
                    elif block.get("type") == "text":
                        parts.append({"text": block.get("text", "")})
                if parts:
                    contents.append({"role": role, "parts": parts})

        if not system_injected and system and contents:
            # Prepend system to first user turn
            first = contents[0]
            if first["role"] == "user":
                first["parts"] = [{"text": f"{system}\n\n{first['parts'][0].get('text', '')}"}] + first["parts"][1:]

        payload = json.dumps({
            "contents": contents,
            "tools": [{"function_declarations": function_declarations}],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }).encode()

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "x-goog-api-key": self.gemini_api_key,
        }, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            preview = e.read().decode(errors="replace")[:_MAX_ERROR_BODY]
            raise RuntimeError(f"Gemini API error: {preview}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error reaching Gemini API: {e.reason}")
        except socket.timeout:
            raise RuntimeError("Gemini API request timed out.")
        except json.JSONDecodeError:
            raise RuntimeError("Gemini API returned malformed JSON.")

        try:
            parts = body["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected Gemini API response structure: {e}")

        text_parts = [p["text"] for p in parts if "text" in p]
        func_calls = [p["functionCall"] for p in parts if "functionCall" in p]

        tool_calls = [
            {"name": fc["name"], "id": fc["name"], "input": fc.get("args", {})}
            for fc in func_calls
        ]

        # Build updated messages for next turn
        raw_messages = list(messages) + [
            {"role": "assistant", "content": [
                *[{"type": "text", "text": t} for t in text_parts],
                *[{"type": "tool_use", "name": fc["name"], "input": fc.get("args", {})} for fc in func_calls],
            ]}
        ]
        if tool_calls:
            raw_messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "name": tc["name"],
                        "content": "",  # caller fills via inject_tool_results_gemini
                    }
                    for tc in tool_calls
                ],
            })

        return {
            "stop_reason": "tool_use" if func_calls else "end_turn",
            "text": " ".join(text_parts).strip(),
            "tool_calls": tool_calls,
            "raw_messages": raw_messages,
        }

    def inject_tool_results_gemini(self, raw_messages: list, tool_calls: list, results: List[str]) -> list:
        """Fill in tool_result content in the last user message."""
        updated = list(raw_messages)
        last = updated[-1]
        updated[-1] = {
            "role": "user",
            "content": [
                {**block, "content": result}
                for block, result in zip(last["content"], results)
            ],
        }
        return updated

    def inject_tool_results(self, raw_messages: list, tool_calls: list, results: List[str]) -> list:
        """Provider-agnostic: fill tool results into the pending message."""
        if self.gemini_api_key:
            return self.inject_tool_results_gemini(raw_messages, tool_calls, results)
        return self.inject_tool_results_anthropic(raw_messages, tool_calls, results)
