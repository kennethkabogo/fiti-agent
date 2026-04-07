import re
from pathlib import Path
from datetime import datetime
from fiti.api_client import APIClient


class QueryEngine:
    def __init__(self, vault, client: APIClient = None):
        self.vault = vault
        self.client = client or APIClient()

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
        elif mode == "data":
            sys_prompt = "You are a data analyst. Based on the provided knowledge base, write a complete Python script using matplotlib that visualizes the answer to the user's question. The script must save the plot to the filename provided in the prompt. Output ONLY valid Python code, nothing else."
            extension = "py"
        else:
            sys_prompt = "You are a research assistant. Based on the provided knowledge base, write a comprehensive markdown report answering the user's question. Use clear headings and bullet points."
            extension = "md"

        prompt = f"""
{sys_prompt}

KNOWLEDGE BASE:
{context}

USER QUESTION: {question}

If mode is data, please save the generated plot to {self.vault.assets_dir}/plot_{int(datetime.now().timestamp())}.png
"""
        response = self.client.call(prompt, max_tokens=2048)

        if mode == "data":
            response = re.sub(r"^```python\n", "", response)
            response = re.sub(r"^```\n", "", response)
            response = re.sub(r"\n```$", "", response)
            response = response.strip()

        slug = re.sub(r'[^a-zA-Z0-9]+', '_', question.lower())[:30].strip('_') or "query"
        timestamp = int(datetime.now().timestamp())
        outfile = self.vault.wiki_queries_dir / f"{slug}_{timestamp}.{extension}"

        with open(outfile, "w") as f:
            f.write(response)

        return outfile
