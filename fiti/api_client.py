import os
import json
import socket
import urllib.request
import urllib.error

GEMINI_MODEL = "gemini-2.5-flash"
ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
_TIMEOUT = 30


class APIClient:
    def __init__(self):
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY")

        if not self.anthropic_api_key and not self.gemini_api_key:
            raise RuntimeError("API Key required. Set GEMINI_API_KEY or ANTHROPIC_API_KEY.")

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
            raise RuntimeError(f"Gemini API error: {e.read().decode()}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error reaching Gemini API: {e.reason}")
        except socket.timeout:
            raise RuntimeError("Gemini API request timed out.")
        except json.JSONDecodeError:
            raise RuntimeError("Gemini API returned malformed JSON.")

        try:
            return body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected Gemini API response structure: {e}\nBody: {body}")

    def call_anthropic(self, prompt: str) -> str:
        url = "https://api.anthropic.com/v1/messages"
        payload = json.dumps({
            "model": ANTHROPIC_MODEL,
            "max_tokens": 1024,
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
            raise RuntimeError(f"Anthropic API error: {e.read().decode()}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error reaching Anthropic API: {e.reason}")
        except socket.timeout:
            raise RuntimeError("Anthropic API request timed out.")
        except json.JSONDecodeError:
            raise RuntimeError("Anthropic API returned malformed JSON.")

        try:
            return body["content"][0]["text"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected Anthropic API response structure: {e}\nBody: {body}")

    def call(self, prompt: str) -> str:
        """Call whichever API is configured, preferring Gemini."""
        if self.gemini_api_key:
            return self.call_gemini(prompt)
        return self.call_anthropic(prompt)
