import os
import re
import shutil
from pathlib import Path
from typing import List

from fiti.config import get_config

ALLOWED_EXTENSIONS = {'.md', '.txt', '.rst', '.csv', '.json'}
_TOPIC_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


class TopicVault:
    def __init__(self, topic_name: str):
        if not _TOPIC_RE.match(topic_name):
            raise ValueError(
                f"Invalid topic name: {topic_name!r}. "
                "Use only letters, digits, hyphens, and underscores."
            )
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
        processed_dir = self.raw_dir / "processed"
        return [
            p for p in self.raw_dir.rglob("*")
            if p.is_file() and not p.is_symlink() and not p.is_relative_to(processed_dir)
        ]

    def ingest_file(self, file_path: Path) -> Path:
        name = file_path.name
        if os.sep in name or (os.altsep and os.altsep in name) or name.startswith(".."):
            raise ValueError(f"Invalid filename: {name!r}")
        if file_path.is_symlink():
            raise ValueError("Symlinks are not allowed.")
        max_bytes = get_config().max_ingest_bytes
        if file_path.stat().st_size > max_bytes:
            raise ValueError(f"File exceeds {max_bytes // (1024 * 1024)}MB limit.")
        if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"File type {file_path.suffix!r} not allowed. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )
        self.ensure_structure()
        dest = self.raw_dir / name
        shutil.copy2(file_path, dest)
        dest.chmod(0o600)
        return dest

    def backup_index(self) -> Path | None:
        """Copy INDEX.md to INDEX.md.bak. Returns backup path, or None if no index exists."""
        if not self.index_file.exists() or self.index_file.is_symlink():
            return None
        backup = self.index_file.with_name("INDEX.md.bak")
        shutil.copy2(self.index_file, backup)
        backup.chmod(0o600)
        return backup

    def stats(self) -> dict:
        """Return counts of files in each vault section."""
        def _count(d: Path) -> int:
            if not d.exists():
                return 0
            return sum(1 for p in d.iterdir() if p.is_file() and not p.is_symlink())

        return {
            "pending": len(self.list_raw_files()),
            "summaries": _count(self.wiki_summaries_dir),
            "concepts": _count(self.wiki_concepts_dir),
            "queries": _count(self.wiki_queries_dir),
        }
