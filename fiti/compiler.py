import re
from pathlib import Path
from fiti.api_client import APIClient


class CompilerEngine:
    def __init__(self, vault, client: APIClient = None):
        self.vault = vault
        self.client = client or APIClient()

    def summarize_and_compile(self, file_path: Path):
        with open(file_path, "r") as f:
            content = f.read()

        with open(self.vault.index_file, "r") as f:
            index_content = f.read()

        prompt = f"""
You are the maintainer of a personal knowledge base wiki for the topic "{self.vault.name}".
I have a new raw document named "{file_path.name}".

Raw Document Content:
<document>
{content}
</document>

Current Wiki Index:
<index>
{index_content}
</index>

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
        response = self.client.call(prompt)

        summary_match = re.search(r"\[\[SUMMARY\]\](.*?)\[\[END_SUMMARY\]\]", response, re.DOTALL)
        index_match = re.search(r"\[\[UPDATED_INDEX\]\](.*?)\[\[END_UPDATED_INDEX\]\]", response, re.DOTALL)

        if summary_match and index_match:
            summary = summary_match.group(1).strip()
            updated_index = index_match.group(1).strip()

            summary_path = self.vault.wiki_summaries_dir / f"{file_path.stem}_summary.md"
            if summary_path.is_symlink():
                raise RuntimeError(f"Output path is a symlink: {summary_path}")
            if self.vault.index_file.is_symlink():
                raise RuntimeError("INDEX.md is a symlink — refusing to overwrite.")

            with open(summary_path, "w") as f:
                f.write(summary)

            with open(self.vault.index_file, "w") as f:
                f.write(updated_index)

            return True
        else:
            raise RuntimeError("Failed to parse LLM output: unexpected response format.")
