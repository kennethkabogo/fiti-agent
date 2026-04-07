import re
from pathlib import Path
from datetime import datetime
from fiti.api_client import APIClient


class QueryEngine:
    def __init__(self, vault, client: APIClient = None):
        self.vault = vault
        self.client = client or APIClient()

    def _gather_context_from_vault(self, vault, label_prefix: str = "") -> str:
        context = ""
        vault_root = vault.base_dir.resolve()

        if vault.index_file.exists() and not vault.index_file.is_symlink():
            with open(vault.index_file, "r") as f:
                context += f"--- {label_prefix}INDEX.md ---\n{f.read()}\n\n"

        if vault.wiki_summaries_dir.exists():
            for p in vault.wiki_summaries_dir.rglob("*.md"):
                if not p.is_symlink() and p.resolve().is_relative_to(vault_root):
                    with open(p, "r") as f:
                        context += f"--- {label_prefix}SUMMARY: {p.name} ---\n{f.read()}\n\n"

        if vault.wiki_concepts_dir.exists():
            for p in vault.wiki_concepts_dir.rglob("*.md"):
                if not p.is_symlink() and p.resolve().is_relative_to(vault_root):
                    with open(p, "r") as f:
                        context += f"--- {label_prefix}CONCEPT: {p.name} ---\n{f.read()}\n\n"

        return context

    def _gather_context(self, extra_vaults: list | None = None) -> str:
        vaults = [self.vault] + (extra_vaults or [])
        multi = len(vaults) > 1
        context = ""
        for vault in vaults:
            prefix = f"[{vault.name}] " if multi else ""
            context += self._gather_context_from_vault(vault, label_prefix=prefix)
        return context

    def execute_query(
        self,
        question: str,
        mode: str,
        extra_vaults: list | None = None,
        output_path: "Path | None" = None,
    ):
        context = self._gather_context(extra_vaults)

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
        if mode == "data":
            print("[WARNING] The generated .py file contains LLM-generated code. Review carefully before executing.")

        response = self.client.call(prompt, max_tokens=2048)

        if mode == "data":
            response = re.sub(r"^```python\n", "", response)
            response = re.sub(r"^```\n", "", response)
            response = re.sub(r"\n```$", "", response)
            response = response.strip()

        if output_path is not None:
            outfile = output_path
        else:
            slug = re.sub(r'[^a-zA-Z0-9]+', '_', question.lower())[:30].strip('_') or "query"
            timestamp = int(datetime.now().timestamp())
            outfile = self.vault.wiki_queries_dir / f"{slug}_{timestamp}.{extension}"

        if outfile.is_symlink():
            raise RuntimeError(f"Output path is a symlink: {outfile}")

        with open(outfile, "w") as f:
            f.write(response)

        return outfile
