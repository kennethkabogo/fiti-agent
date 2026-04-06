import shutil
from pathlib import Path
from typing import List

class TopicVault:
    def __init__(self, topic_name: str):
        self.name = topic_name
        self.base_dir = Path.home() / ".fiti" / "topics" / topic_name
        self.raw_dir = self.base_dir / "raw"
        self.wiki_dir = self.base_dir / "wiki"
        self.wiki_concepts_dir = self.wiki_dir / "concepts"
        self.wiki_summaries_dir = self.wiki_dir / "summaries"
        self.wiki_queries_dir = self.wiki_dir / "queries"
        self.assets_dir = self.base_dir / "assets"
        self.index_file = self.wiki_dir / "INDEX.md"

    def ensure_structure(self):
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.wiki_concepts_dir.mkdir(parents=True, exist_ok=True)
        self.wiki_summaries_dir.mkdir(parents=True, exist_ok=True)
        self.wiki_queries_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_file.exists():
            with open(self.index_file, "w") as f:
                f.write(f"# {self.name} Index\n\nNo concepts defined yet.\n")

    def exists(self) -> bool:
        return self.base_dir.exists()

    def list_raw_files(self) -> List[Path]:
        if not self.raw_dir.exists():
            return []
        return [p for p in self.raw_dir.rglob("*") if p.is_file()]

    def ingest_file(self, file_path: Path) -> Path:
        self.ensure_structure()
        dest = self.raw_dir / file_path.name
        shutil.copy2(file_path, dest)
        return dest
