import re
from typing import List
from fiti.api_client import APIClient

_COMPILER_TAGS = {"SUMMARY", "END_SUMMARY", "UPDATED_INDEX", "END_UPDATED_INDEX", "OPTIMIZED_INDEX", "END_OPTIMIZED_INDEX"}


class LinterEngine:
    def __init__(self, vault, client: APIClient = None):
        self.vault = vault
        self.client = client or APIClient()

    def find_broken_links(self) -> List[str]:
        broken = []
        wiki_files = list(self.vault.wiki_dir.rglob("*.md"))

        valid_concepts = {p.stem for p in self.vault.wiki_concepts_dir.rglob("*.md")}

        for f in wiki_files:
            with open(f, "r") as file:
                content = file.read()
                links = re.findall(r"\[\[(.*?)\]\]", content)
                for link in links:
                    if link in _COMPILER_TAGS:
                        continue
                    if link not in valid_concepts:
                        broken.append(f"Broken link '[[{link}]]' found in {f.name}")
        return broken

    def run_health_check(self, fix: bool = False):
        index_content = ""
        if self.vault.index_file.exists():
            with open(self.vault.index_file, "r") as f:
                index_content = f.read()

        prompt = f"""
You are the health-checker for a personal knowledge base.
Review this current Index:
---
{index_content}
---
Identify any structural issues: duplicate or overlapping concepts, missing overarching themes, or poor organization.
"""
        if fix:
            prompt += "\nOUTPUT REQUIREMENT: Return a completely rewritten, optimized version of the INDEX.md wrapped in [[OPTIMIZED_INDEX]] and [[END_OPTIMIZED_INDEX]] tags. Do not return anything else."
            response = self.client.call(prompt)

            match = re.search(r"\[\[OPTIMIZED_INDEX\]\](.*?)\[\[END_OPTIMIZED_INDEX\]\]", response, re.DOTALL)
            if match:
                opt_index = match.group(1).strip()
                with open(self.vault.index_file, "w") as f:
                    f.write(opt_index)
                return "Index has been successfully rebuilt and optimized."
            else:
                return f"Failed to parse optimization. Raw response:\n{response}"
        else:
            prompt += "\nOUTPUT REQUIREMENT: Provide a 3-bullet-point summary of recommended fixes for the index structure."
            return self.client.call(prompt)
