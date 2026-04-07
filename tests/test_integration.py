"""
Integration tests using canned fixture responses.

These tests exercise the full compile/query pipeline end-to-end without
making real API calls. The fixture JSON files in tests/fixtures/ stand in
for actual Anthropic/Gemini HTTP responses.
"""
import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from fiti.api_client import APIClient
from fiti.compiler import CompilerEngine
from fiti.query import QueryEngine
from fiti.vault import TopicVault

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _mock_urlopen_fixture(fixture_name: str):
    """Return a fake urlopen that serves a fixture file."""
    body = _load_fixture(fixture_name)

    def fake_urlopen(req, timeout=None):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = body
        return mock_resp

    return fake_urlopen


def make_client(anthropic: bool = True):
    env = {"ANTHROPIC_API_KEY": "test-key"} if anthropic else {"GEMINI_API_KEY": "test-key"}
    with patch.dict("os.environ", env, clear=True):
        return APIClient()


# ── Compile integration ────────────────────────────────────────────────────

def test_compile_anthropic_end_to_end(tmp_path):
    """Full compile flow with canned Anthropic response."""
    vault = TopicVault.__new__(TopicVault)
    vault.name = "test"
    vault.base_dir = tmp_path
    vault.raw_dir = tmp_path / "raw"
    vault.wiki_dir = tmp_path / "wiki"
    vault.wiki_concepts_dir = tmp_path / "wiki" / "concepts"
    vault.wiki_summaries_dir = tmp_path / "wiki" / "summaries"
    vault.wiki_queries_dir = tmp_path / "wiki" / "queries"
    vault.assets_dir = tmp_path / "assets"
    vault.index_file = tmp_path / "wiki" / "INDEX.md"
    vault.ensure_structure()

    raw_file = vault.raw_dir / "note.md"
    raw_file.write_text("# Python Basics\n\nPython is a programming language.")

    client = make_client(anthropic=True)
    compiler = CompilerEngine(vault, client)

    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_fixture("anthropic_compile_response.json")):
        result = compiler.summarize_and_compile(raw_file)

    assert result is True
    summary_file = vault.wiki_summaries_dir / "note_summary.md"
    assert summary_file.exists()
    assert "Python" in summary_file.read_text()
    assert "python_basics" in vault.index_file.read_text()


def test_compile_gemini_end_to_end(tmp_path):
    """Full compile flow with canned Gemini response."""
    vault = TopicVault.__new__(TopicVault)
    vault.name = "test"
    vault.base_dir = tmp_path
    vault.raw_dir = tmp_path / "raw"
    vault.wiki_dir = tmp_path / "wiki"
    vault.wiki_concepts_dir = tmp_path / "wiki" / "concepts"
    vault.wiki_summaries_dir = tmp_path / "wiki" / "summaries"
    vault.wiki_queries_dir = tmp_path / "wiki" / "queries"
    vault.assets_dir = tmp_path / "assets"
    vault.index_file = tmp_path / "wiki" / "INDEX.md"
    vault.ensure_structure()

    raw_file = vault.raw_dir / "note.md"
    raw_file.write_text("# Python Basics\n\nPython is a programming language.")

    env = {"GEMINI_API_KEY": "test-key"}
    with patch.dict("os.environ", env, clear=True):
        client = APIClient()
    compiler = CompilerEngine(vault, client)

    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_fixture("gemini_compile_response.json")):
        result = compiler.summarize_and_compile(raw_file)

    assert result is True
    summary_file = vault.wiki_summaries_dir / "note_summary.md"
    assert summary_file.exists()
    assert "python_basics" in vault.index_file.read_text()


def test_compile_creates_atomic_index(tmp_path):
    """INDEX.md is written atomically — no .tmp file should remain."""
    vault = TopicVault.__new__(TopicVault)
    vault.name = "test"
    vault.base_dir = tmp_path
    vault.raw_dir = tmp_path / "raw"
    vault.wiki_dir = tmp_path / "wiki"
    vault.wiki_concepts_dir = tmp_path / "wiki" / "concepts"
    vault.wiki_summaries_dir = tmp_path / "wiki" / "summaries"
    vault.wiki_queries_dir = tmp_path / "wiki" / "queries"
    vault.assets_dir = tmp_path / "assets"
    vault.index_file = tmp_path / "wiki" / "INDEX.md"
    vault.ensure_structure()

    raw_file = vault.raw_dir / "note.md"
    raw_file.write_text("content")

    client = make_client(anthropic=True)
    compiler = CompilerEngine(vault, client)

    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_fixture("anthropic_compile_response.json")):
        compiler.summarize_and_compile(raw_file)

    tmp_files = list(vault.wiki_dir.glob("*.tmp"))
    assert tmp_files == [], "No .tmp files should remain after atomic write"


def test_compile_creates_index_backup(tmp_path):
    """A .bak file of INDEX.md should be created before compile."""
    vault = TopicVault.__new__(TopicVault)
    vault.name = "test"
    vault.base_dir = tmp_path
    vault.raw_dir = tmp_path / "raw"
    vault.wiki_dir = tmp_path / "wiki"
    vault.wiki_concepts_dir = tmp_path / "wiki" / "concepts"
    vault.wiki_summaries_dir = tmp_path / "wiki" / "summaries"
    vault.wiki_queries_dir = tmp_path / "wiki" / "queries"
    vault.assets_dir = tmp_path / "assets"
    vault.index_file = tmp_path / "wiki" / "INDEX.md"
    vault.ensure_structure()

    raw_file = vault.raw_dir / "note.md"
    raw_file.write_text("content")

    client = make_client(anthropic=True)
    compiler = CompilerEngine(vault, client)

    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_fixture("anthropic_compile_response.json")):
        compiler.summarize_and_compile(raw_file)

    bak = vault.wiki_dir / "INDEX.md.bak"
    assert bak.exists(), "INDEX.md.bak should be created before compile"


# ── Query integration ──────────────────────────────────────────────────────

def test_query_end_to_end(tmp_path):
    """Full query flow with canned Anthropic response."""
    vault = TopicVault.__new__(TopicVault)
    vault.name = "test"
    vault.base_dir = tmp_path
    vault.raw_dir = tmp_path / "raw"
    vault.wiki_dir = tmp_path / "wiki"
    vault.wiki_concepts_dir = tmp_path / "wiki" / "concepts"
    vault.wiki_summaries_dir = tmp_path / "wiki" / "summaries"
    vault.wiki_queries_dir = tmp_path / "wiki" / "queries"
    vault.assets_dir = tmp_path / "assets"
    vault.index_file = tmp_path / "wiki" / "INDEX.md"
    vault.ensure_structure()

    client = make_client(anthropic=True)
    engine = QueryEngine(vault, client)

    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_fixture("anthropic_query_response.json")):
        outfile = engine.execute_query("Tell me about Python", "report")

    assert outfile.exists()
    content = outfile.read_text()
    assert "Python Report" in content


def test_query_multi_vault_gathers_both_contexts(tmp_path):
    """Multi-vault query includes context from both vaults."""
    def make_vault(name: str, content: str) -> TopicVault:
        vdir = tmp_path / name
        v = TopicVault.__new__(TopicVault)
        v.name = name
        v.base_dir = vdir
        v.raw_dir = vdir / "raw"
        v.wiki_dir = vdir / "wiki"
        v.wiki_concepts_dir = vdir / "wiki" / "concepts"
        v.wiki_summaries_dir = vdir / "wiki" / "summaries"
        v.wiki_queries_dir = vdir / "wiki" / "queries"
        v.assets_dir = vdir / "assets"
        v.index_file = vdir / "wiki" / "INDEX.md"
        v.ensure_structure()
        v.index_file.write_text(content)
        return v

    vault_a = make_vault("alpha", "# Alpha Index\n\nAlpha content.")
    vault_b = make_vault("beta", "# Beta Index\n\nBeta content.")

    client = make_client(anthropic=True)
    engine = QueryEngine(vault_a, client)
    context = engine._gather_context(extra_vaults=[vault_b])

    assert "Alpha content" in context
    assert "Beta content" in context
    assert "[alpha]" in context
    assert "[beta]" in context


# ── Token usage integration ────────────────────────────────────────────────

def test_usage_accumulated_after_anthropic_compile(tmp_path):
    """Token usage from compile is tracked on the APIClient."""
    vault = TopicVault.__new__(TopicVault)
    vault.name = "test"
    vault.base_dir = tmp_path
    vault.raw_dir = tmp_path / "raw"
    vault.wiki_dir = tmp_path / "wiki"
    vault.wiki_concepts_dir = tmp_path / "wiki" / "concepts"
    vault.wiki_summaries_dir = tmp_path / "wiki" / "summaries"
    vault.wiki_queries_dir = tmp_path / "wiki" / "queries"
    vault.assets_dir = tmp_path / "assets"
    vault.index_file = tmp_path / "wiki" / "INDEX.md"
    vault.ensure_structure()

    raw_file = vault.raw_dir / "note.md"
    raw_file.write_text("content")

    client = make_client(anthropic=True)
    compiler = CompilerEngine(vault, client)

    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_fixture("anthropic_compile_response.json")):
        compiler.summarize_and_compile(raw_file)

    usage = client.get_usage()
    assert usage["input_tokens"] == 120
    assert usage["output_tokens"] == 85


def test_usage_accumulated_after_gemini_compile(tmp_path):
    """Token usage from Gemini compile is tracked on the APIClient."""
    vault = TopicVault.__new__(TopicVault)
    vault.name = "test"
    vault.base_dir = tmp_path
    vault.raw_dir = tmp_path / "raw"
    vault.wiki_dir = tmp_path / "wiki"
    vault.wiki_concepts_dir = tmp_path / "wiki" / "concepts"
    vault.wiki_summaries_dir = tmp_path / "wiki" / "summaries"
    vault.wiki_queries_dir = tmp_path / "wiki" / "queries"
    vault.assets_dir = tmp_path / "assets"
    vault.index_file = tmp_path / "wiki" / "INDEX.md"
    vault.ensure_structure()

    raw_file = vault.raw_dir / "note.md"
    raw_file.write_text("content")

    env = {"GEMINI_API_KEY": "test-key"}
    with patch.dict("os.environ", env, clear=True):
        client = APIClient()
    compiler = CompilerEngine(vault, client)

    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_fixture("gemini_compile_response.json")):
        compiler.summarize_and_compile(raw_file)

    usage = client.get_usage()
    assert usage["input_tokens"] == 100    # promptTokenCount
    assert usage["output_tokens"] == 75    # candidatesTokenCount


def test_usage_accumulates_across_multiple_calls(tmp_path):
    """Compiling two files accumulates usage from both LLM calls."""
    vault = TopicVault.__new__(TopicVault)
    vault.name = "test"
    vault.base_dir = tmp_path
    vault.raw_dir = tmp_path / "raw"
    vault.wiki_dir = tmp_path / "wiki"
    vault.wiki_concepts_dir = tmp_path / "wiki" / "concepts"
    vault.wiki_summaries_dir = tmp_path / "wiki" / "summaries"
    vault.wiki_queries_dir = tmp_path / "wiki" / "queries"
    vault.assets_dir = tmp_path / "assets"
    vault.index_file = tmp_path / "wiki" / "INDEX.md"
    vault.ensure_structure()

    file_a = vault.raw_dir / "a.md"
    file_b = vault.raw_dir / "b.md"
    file_a.write_text("content a")
    file_b.write_text("content b")

    client = make_client(anthropic=True)
    compiler = CompilerEngine(vault, client)
    fixture_body = _load_fixture("anthropic_compile_response.json")

    def fake_urlopen(req, timeout=None):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = fixture_body
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        compiler.summarize_and_compile(file_a)
        # Re-write INDEX.md so second compile finds expected content
        vault.index_file.write_text("# test Index\n")
        compiler.summarize_and_compile(file_b)

    usage = client.get_usage()
    assert usage["input_tokens"] == 240    # 120 * 2
    assert usage["output_tokens"] == 170   # 85 * 2


# ── Lock file integration ──────────────────────────────────────────────────

def test_lock_prevents_concurrent_access(tmp_path):
    """acquire_lock raises RuntimeError when vault is already locked."""
    vault = TopicVault("test-lock")
    vault.base_dir = tmp_path
    vault.base_dir.mkdir(parents=True, exist_ok=True)

    vault.acquire_lock()
    try:
        with pytest.raises(RuntimeError, match="locked by PID"):
            vault.acquire_lock()
    finally:
        vault.release_lock()


def test_lock_cleans_up_on_release(tmp_path):
    """Lock file is removed after release_lock."""
    vault = TopicVault("test-lock2")
    vault.base_dir = tmp_path
    vault.base_dir.mkdir(parents=True, exist_ok=True)

    vault.acquire_lock()
    assert vault.lock_file.exists()
    vault.release_lock()
    assert not vault.lock_file.exists()


def test_locked_context_manager_releases_on_exception(tmp_path):
    """locked() context manager releases the lock even if an exception is raised."""
    vault = TopicVault("test-lock3")
    vault.base_dir = tmp_path
    vault.base_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError):
        with vault.locked():
            raise ValueError("oops")

    assert not vault.lock_file.exists()
