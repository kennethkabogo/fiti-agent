"""Tests for new CLI commands: list, delete, search, config."""
import pytest
from pathlib import Path
from unittest.mock import patch

from fiti.vault import TopicVault
from fiti.state import StateManager


def _make_vault(tmp_path, name):
    with patch.object(Path, "home", return_value=tmp_path):
        v = TopicVault(name)
    v.ensure_structure()
    return v


def _make_state(tmp_path):
    with patch.object(Path, "home", return_value=tmp_path):
        return StateManager()


# ── fiti list ───────────────────────────────────────────────────────────────

def test_cmd_list_no_vaults(tmp_path, capsys):
    from fiti.cli import cmd_list
    with patch.object(Path, "home", return_value=tmp_path):
        cmd_list(None)
    out = capsys.readouterr().out
    assert "No vaults found" in out


def test_cmd_list_shows_vaults(tmp_path, capsys):
    _make_vault(tmp_path, "python")
    _make_vault(tmp_path, "rust")
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.cli import cmd_list
        cmd_list(None)
    out = capsys.readouterr().out
    assert "python" in out
    assert "rust" in out


def test_cmd_list_marks_active_topic(tmp_path, capsys):
    _make_vault(tmp_path, "python")
    _make_vault(tmp_path, "rust")
    state = _make_state(tmp_path)
    state.set_active_topic("python")
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.cli import cmd_list
        # Reset colors to plain text for assertion
        with patch("fiti.colors._tty", return_value=False):
            cmd_list(None)
    out = capsys.readouterr().out
    # Active topic should have marker
    lines = out.splitlines()
    python_line = next(l for l in lines if "python" in l)
    assert "*" in python_line
    rust_line = next(l for l in lines if "rust" in l)
    assert "*" not in rust_line


# ── fiti delete ─────────────────────────────────────────────────────────────

def test_cmd_delete_with_yes_flag(tmp_path, capsys):
    _make_vault(tmp_path, "python")
    args = type("A", (), {"topic": "python", "yes": True})()
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.cli import cmd_delete
        cmd_delete(args)
    out = capsys.readouterr().out
    assert "Deleted" in out
    vault_dir = tmp_path / ".fiti" / "topics" / "python"
    assert not vault_dir.exists()


def test_cmd_delete_clears_active_topic(tmp_path, capsys):
    _make_vault(tmp_path, "python")
    state = _make_state(tmp_path)
    state.set_active_topic("python")
    args = type("A", (), {"topic": "python", "yes": True})()
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.cli import cmd_delete
        cmd_delete(args)
    state2 = _make_state(tmp_path)
    assert state2.get_active_topic() in (None, "")


def test_cmd_delete_nonexistent_exits(tmp_path, capsys):
    args = type("A", (), {"topic": "nope", "yes": True})()
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.cli import cmd_delete
        with pytest.raises(SystemExit):
            cmd_delete(args)


def test_cmd_delete_confirmation_wrong_name_aborts(tmp_path, capsys):
    _make_vault(tmp_path, "python")
    args = type("A", (), {"topic": "python", "yes": False})()
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.cli import cmd_delete
        with patch("builtins.input", return_value="wrong-name"):
            with pytest.raises(SystemExit):
                cmd_delete(args)
    # Vault should still exist
    assert (tmp_path / ".fiti" / "topics" / "python").exists()


def test_cmd_delete_confirmation_correct_name_deletes(tmp_path, capsys):
    _make_vault(tmp_path, "python")
    args = type("A", (), {"topic": "python", "yes": False})()
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.cli import cmd_delete
        with patch("builtins.input", return_value="python"):
            cmd_delete(args)
    assert not (tmp_path / ".fiti" / "topics" / "python").exists()


# ── fiti search ─────────────────────────────────────────────────────────────

def test_cmd_search_finds_matches(tmp_path, capsys):
    vault = _make_vault(tmp_path, "python")
    state = _make_state(tmp_path)
    state.set_active_topic("python")
    (vault.wiki_summaries_dir / "decorators.md").write_text(
        "A decorator wraps a function.\nDecorators are useful."
    )
    args = type("A", (), {"keyword": "decorator", "all": False})()
    with patch.object(Path, "home", return_value=tmp_path):
        with patch("fiti.colors._tty", return_value=False):
            from fiti.cli import cmd_search
            cmd_search(args)
    out = capsys.readouterr().out
    assert "decorator" in out.lower()
    assert "2 matches" in out


def test_cmd_search_no_matches(tmp_path, capsys):
    vault = _make_vault(tmp_path, "python")
    state = _make_state(tmp_path)
    state.set_active_topic("python")
    (vault.wiki_summaries_dir / "note.md").write_text("Python is great.")
    args = type("A", (), {"keyword": "rust", "all": False})()
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.cli import cmd_search
        cmd_search(args)
    out = capsys.readouterr().out
    assert "No matches" in out


def test_cmd_search_skips_symlinks(tmp_path, capsys):
    vault = _make_vault(tmp_path, "python")
    state = _make_state(tmp_path)
    state.set_active_topic("python")
    real = tmp_path / "external.md"
    real.write_text("secret decorator content")
    link = vault.wiki_summaries_dir / "link.md"
    link.symlink_to(real)
    args = type("A", (), {"keyword": "secret", "all": False})()
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.cli import cmd_search
        cmd_search(args)
    out = capsys.readouterr().out
    assert "No matches" in out


# ── fiti config ─────────────────────────────────────────────────────────────

def test_cmd_config_shows_defaults(tmp_path, capsys):
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.config import reset_config
        reset_config()
        from fiti.cli import cmd_config
        cmd_config(None)
    out = capsys.readouterr().out
    assert "gemini_model" in out
    assert "retry_attempts" in out
    assert "timeout" in out
