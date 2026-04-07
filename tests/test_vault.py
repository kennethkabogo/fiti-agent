import pytest
from pathlib import Path
from unittest.mock import patch

from fiti.vault import TopicVault


def make_vault(tmp_path, name="test-topic"):
    with patch.object(Path, "home", return_value=tmp_path):
        return TopicVault(name)


def test_vault_exists_false_before_creation(tmp_path):
    vault = make_vault(tmp_path)
    assert not vault.exists()


def test_vault_ensure_structure_creates_dirs(tmp_path):
    vault = make_vault(tmp_path)
    vault.ensure_structure()
    assert vault.raw_dir.exists()
    assert vault.wiki_concepts_dir.exists()
    assert vault.wiki_summaries_dir.exists()
    assert vault.wiki_queries_dir.exists()
    assert vault.assets_dir.exists()
    assert vault.index_file.exists()


def test_vault_exists_true_after_creation(tmp_path):
    vault = make_vault(tmp_path)
    vault.ensure_structure()
    assert vault.exists()


def test_list_raw_files_empty_before_ingest(tmp_path):
    vault = make_vault(tmp_path)
    vault.ensure_structure()
    assert vault.list_raw_files() == []


def test_list_raw_files_excludes_processed(tmp_path):
    vault = make_vault(tmp_path)
    vault.ensure_structure()
    processed_dir = vault.raw_dir / "processed"
    processed_dir.mkdir()
    (vault.raw_dir / "pending.md").write_text("pending")
    (processed_dir / "done.md").write_text("done")

    files = vault.list_raw_files()
    names = [f.name for f in files]
    assert "pending.md" in names
    assert "done.md" not in names


def test_ingest_file_copies_to_raw(tmp_path):
    vault = make_vault(tmp_path)
    vault.ensure_structure()
    src = tmp_path / "note.md"
    src.write_text("hello")
    vault.ingest_file(src)
    assert (vault.raw_dir / "note.md").exists()


def test_ingest_file_rejects_path_traversal(tmp_path):
    vault = make_vault(tmp_path)
    vault.ensure_structure()
    src = tmp_path / "note.md"
    src.write_text("hello")
    # Simulate a file_path whose .name contains a separator
    evil = Path("/some/dir/../note.md")
    # Rename src so its .name mimics traversal via monkey-patching name property
    import types
    fake = types.SimpleNamespace(name="../evil.md", __fspath__=lambda: str(src))
    # Build a minimal Path-like; just test the guard directly
    from fiti import vault as vault_mod
    import os
    # Directly test: a filename with os.sep should raise
    class FakePath:
        name = f"..{os.sep}evil.md"
    with pytest.raises(ValueError, match="Invalid filename"):
        vault_mod.TopicVault.__dict__["ingest_file"](vault, FakePath())
