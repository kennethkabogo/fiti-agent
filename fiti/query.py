import os
import json
import urllib.request
import urllib.error
import re
from pathlib import Path
from datetime import datetime

class QueryEngine:
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
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = json.loads(resp.read())
                return body["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Gemini API error: {e.read().decode()}")

    def call_anthropic(self, prompt: str) -> str:
        url = "https://api.anthropic.com/v1/messages"
        payload = json.dumps({
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={
            "x-api-key": self.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = json.loads(resp.read())
                return body["content"][0]["text"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Anthropic API error: {e.read().decode()}")

    def _gather_context(self) -> str:
        context = ""
        if self.vault.index_file.exists():
            with open(self.vault.index_file, "r") as f:
                context += f"--- INDEX.md ---\n{f.read()}\n\n"
                
        if self.vault.wiki_summaries_dir.exists():
            for p in self.vault.wiki_summaries_dir.rglob("*.md"):
                with open(p, "r") as f:
                    context += f"--- SUMMARY: {p.name} ---\n{f.read()}\n\n"
                    
        if self.vault.wiki_concepts_dir.exists():
            for p in self.vault.wiki_concepts_dir.rglob("*.md"):
                with open(p, "r") as f:
                    context += f"--- CONCEPT: {p.name} ---\n{f.read()}\n\n"
        
        return context

    def execute_query(self, question: str, mode: str):
        context = self._gather_context()
        
        if mode == "slides":
            sys_prompt = "You are a presentation generator. Based on the provided knowledge base, answer the user's question by formatting the output as a Marp markdown presentation. Start with Marp frontmatter (e.g. ---\nmarp: true\ntheme: default\n---). Separate slides with `---`."
            extension = "md"
            out_dir = self.vault.wiki_queries_dir
        elif mode == "data":
            sys_prompt = "You are a data analyst. Based on the provided knowledge base, write a complete Python script using matplotlib that visualizes the answer to the user's question. The script must save the plot to the filename provided in the prompt. Output ONLY valid Python code, nothing else."
            extension = "py"
            out_dir = self.vault.wiki_queries_dir
        else:
            sys_prompt = "You are a research assistant. Based on the provided knowledge base, write a comprehensive markdown report answering the user's question. Use clear headings and bullet points."
            extension = "md"
            out_dir = self.vault.wiki_queries_dir

        prompt = f"""
{sys_prompt}

KNOWLEDGE BASE:
{context}

USER QUESTION: {question}

If mode is data, please save the generated plot to {self.vault.assets_dir}/plot_{int(datetime.now().timestamp())}.png
"""
        response = self.call_gemini(prompt) if self.gemini_api_key else self.call_anthropic(prompt)

        if mode == "data":
            response = re.sub(r"^```python\n", "", response)
            response = re.sub(r"^```\n", "", response)
            response = re.sub(r"\n```$", "", response)
            response = response.strip()

        slug = re.sub(r'[^a-zA-Z0-9]+', '_', question.lower())[:30].strip('_')
        timestamp = int(datetime.now().timestamp())
        outfile = out_dir / f"{slug}_{timestamp}.{extension}"
        
        with open(outfile, "w") as f:
            f.write(response)

        return outfile
