import os
import stat
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


def test_list_raw_files_excludes_symlinks(tmp_path):
    vault = make_vault(tmp_path)
    vault.ensure_structure()
    real = tmp_path / "real.md"
    real.write_text("real")
    link = vault.raw_dir / "link.md"
    link.symlink_to(real)
    (vault.raw_dir / "normal.md").write_text("normal")

    names = [f.name for f in vault.list_raw_files()]
    assert "normal.md" in names
    assert "link.md" not in names


def test_ingest_file_copies_to_raw(tmp_path):
    vault = make_vault(tmp_path)
    vault.ensure_structure()
    src = tmp_path / "note.md"
    src.write_text("hello")
    vault.ingest_file(src)
    assert (vault.raw_dir / "note.md").exists()


def test_ingest_file_sets_permissions_600(tmp_path):
    vault = make_vault(tmp_path)
    vault.ensure_structure()
    src = tmp_path / "note.md"
    src.write_text("hello")
    dest = vault.ingest_file(src)
    mode = oct(stat.S_IMODE(dest.stat().st_mode))
    assert mode == "0o600"


def test_ingest_file_rejects_symlink(tmp_path):
    vault = make_vault(tmp_path)
    vault.ensure_structure()
    real = tmp_path / "real.md"
    real.write_text("data")
    link = tmp_path / "link.md"
    link.symlink_to(real)
    with pytest.raises(ValueError, match="Symlinks are not allowed"):
        vault.ingest_file(link)


def test_ingest_file_rejects_oversized_file(tmp_path):
    vault = make_vault(tmp_path)
    vault.ensure_structure()
    big = tmp_path / "big.md"
    big.write_bytes(b"x" * (11 * 1024 * 1024))  # 11 MB
    with pytest.raises(ValueError, match="exceeds"):
        vault.ingest_file(big)


def test_ingest_file_rejects_disallowed_extension(tmp_path):
    vault = make_vault(tmp_path)
    vault.ensure_structure()
    exe = tmp_path / "malware.exe"
    exe.write_bytes(b"MZ")
    with pytest.raises(ValueError, match="not allowed"):
        vault.ingest_file(exe)


def test_ingest_file_rejects_path_traversal(tmp_path):
    vault = make_vault(tmp_path)
    vault.ensure_structure()
    from fiti import vault as vault_mod

    class FakePath:
        name = f"..{os.sep}evil.md"

    with pytest.raises(ValueError, match="Invalid filename"):
        vault_mod.TopicVault.__dict__["ingest_file"](vault, FakePath())


def test_vault_init_rejects_invalid_topic_name(tmp_path):
    with patch.object(Path, "home", return_value=tmp_path):
        with pytest.raises(ValueError, match="Invalid topic name"):
            TopicVault("../evil")


def test_vault_init_rejects_spaces_in_name(tmp_path):
    with patch.object(Path, "home", return_value=tmp_path):
        with pytest.raises(ValueError, match="Invalid topic name"):
            TopicVault("my topic")
