import os
import json
import urllib.request
import urllib.error
from pathlib import Path
import re

class CompilerEngine:
    def __init__(self, vault):
        self.vault = vault
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY")

        if not self.anthropic_api_key and not self.gemini_api_key:
            raise RuntimeError("API Key required. Set GEMINI_API_KEY or ANTHROPIC_API_KEY.")

    def call_gemini(self, prompt: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.gemini_api_key}"
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}]
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
                return body["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Gemini API error: {e.read().decode()}")

    def call_anthropic(self, prompt: str) -> str:
        url = "https://api.anthropic.com/v1/messages"
        payload = json.dumps({
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={
            "x-api-key": self.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
                return body["content"][0]["text"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Anthropic API error: {e.read().decode()}")

    def summarize_and_compile(self, file_path: Path):
        with open(file_path, "r") as f:
            content = f.read()

        with open(self.vault.index_file, "r") as f:
            index_content = f.read()

        prompt = f"""
You are the maintainer of a personal knowledge base wiki for the topic "{self.vault.name}".
I have a new raw document named "{file_path.name}".

Raw Document Content:
---
{content}
---

Current Wiki Index:
---
{index_content}
---

Task 1: Summarize the Raw Document. 
Task 2: Identify any core concepts that should be added to the Index.

Output your response EXACTLY in this format:
[[SUMMARY]]
(Your markdown summary here)
[[END_SUMMARY]]

[[UPDATED_INDEX]]
(The entirely rewritten and updated INDEX.md content here)
[[END_UPDATED_INDEX]]
"""
        if self.gemini_api_key:
            response = self.call_gemini(prompt)
        else:
            response = self.call_anthropic(prompt)

        summary_match = re.search(r"\[\[SUMMARY\]\](.*?)\[\[END_SUMMARY\]\]", response, re.DOTALL)
        index_match = re.search(r"\[\[UPDATED_INDEX\]\](.*?)\[\[END_UPDATED_INDEX\]\]", response, re.DOTALL)

        if summary_match and index_match:
            summary = summary_match.group(1).strip()
            updated_index = index_match.group(1).strip()
            
            summary_path = self.vault.wiki_summaries_dir / f"{file_path.stem}_summary.md"
            with open(summary_path, "w") as f:
                f.write(summary)
            
            with open(self.vault.index_file, "w") as f:
                f.write(updated_index)
            
            return True
        else:
            raise RuntimeError(f"Failed to parse LLM output: {response}")
