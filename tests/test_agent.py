import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from fiti.vault import TopicVault
from fiti.api_client import APIClient
from fiti.agent import AgentExecutor


def make_vault_and_executor(tmp_path):
    with patch.object(Path, "home", return_value=tmp_path):
        vault = TopicVault("test-topic")
    vault.ensure_structure()
    client = MagicMock(spec=APIClient)
    client.gemini_api_key = None
    client.anthropic_api_key = "key"
    executor = AgentExecutor(vault, client)
    return vault, executor


# ── Tool: fetch_url ─────────────────────────────────────────────────────────

def test_fetch_url_rejects_http(tmp_path):
    _, executor = make_vault_and_executor(tmp_path)
    result = executor._fetch_url("http://evil.com/data.md", "data.md")
    assert "error" in result
    assert "HTTPS" in result["error"]


def test_fetch_url_rejects_ftp(tmp_path):
    _, executor = make_vault_and_executor(tmp_path)
    result = executor._fetch_url("ftp://example.com/file.md", "file.md")
    assert "error" in result


# ── Tool: read_file ─────────────────────────────────────────────────────────

def test_read_file_blocks_path_traversal(tmp_path):
    _, executor = make_vault_and_executor(tmp_path)
    result = executor._read_file("../../etc/passwd")
    assert "error" in result
    assert "traversal" in result["error"].lower() or "blocked" in result["error"].lower()


def test_read_file_blocks_symlink(tmp_path):
    vault, executor = make_vault_and_executor(tmp_path)
    real = tmp_path / "secret.txt"
    real.write_text("secret")
    link = vault.wiki_summaries_dir / "link.md"
    link.symlink_to(real)
    result = executor._read_file("wiki/summaries/link.md")
    assert "error" in result
    assert "symlink" in result["error"].lower()


def test_read_file_returns_content(tmp_path):
    vault, executor = make_vault_and_executor(tmp_path)
    (vault.wiki_summaries_dir / "note.md").write_text("hello world")
    result = executor._read_file("wiki/summaries/note.md")
    assert "content" in result
    assert "hello world" in result["content"]


def test_read_file_truncates_large_files(tmp_path):
    vault, executor = make_vault_and_executor(tmp_path)
    big_content = "a" * 20_000
    (vault.wiki_summaries_dir / "big.md").write_text(big_content)
    result = executor._read_file("wiki/summaries/big.md")
    assert "content" in result
    assert len(result["content"]) <= 10_100  # 10k + truncation message


# ── Tool: ingest_text ───────────────────────────────────────────────────────

def test_ingest_text_rejects_invalid_filename(tmp_path):
    _, executor = make_vault_and_executor(tmp_path)
    result = executor._ingest_text("some content", "../evil.md")
    assert "error" in result


def test_ingest_text_rejects_path_separator(tmp_path):
    _, executor = make_vault_and_executor(tmp_path)
    result = executor._ingest_text("content", "sub/dir/file.md")
    assert "error" in result


def test_ingest_text_rejects_disallowed_extension(tmp_path):
    _, executor = make_vault_and_executor(tmp_path)
    result = executor._ingest_text("#!/bin/bash", "script.sh")
    assert "error" in result


def test_ingest_text_succeeds(tmp_path):
    vault, executor = make_vault_and_executor(tmp_path)
    result = executor._ingest_text("# Hello\n\nWorld.", "hello.md")
    assert "result" in result
    assert (vault.raw_dir / "hello.md").read_text() == "# Hello\n\nWorld."


# ── Tool: write_concept ─────────────────────────────────────────────────────

def test_write_concept_creates_file(tmp_path):
    vault, executor = make_vault_and_executor(tmp_path)
    result = executor._write_concept("Decorators", "# Decorators\n\nA decorator wraps a function.")
    assert "result" in result
    # slug of "Decorators" → "decorators"
    assert (vault.wiki_concepts_dir / "decorators.md").exists()


def test_write_concept_sanitizes_title(tmp_path):
    vault, executor = make_vault_and_executor(tmp_path)
    result = executor._write_concept("Hello World / Python!", "content")
    assert "result" in result
    # Should create some valid filename
    files = list(vault.wiki_concepts_dir.glob("*.md"))
    assert len(files) == 1


# ── Tool: list_vault_files ──────────────────────────────────────────────────

def test_list_vault_files_returns_empty_for_fresh_vault(tmp_path):
    _, executor = make_vault_and_executor(tmp_path)
    result = executor._list_vault_files("summaries")
    assert result == {"files": []}


def test_list_vault_files_unknown_category(tmp_path):
    _, executor = make_vault_and_executor(tmp_path)
    result = executor._list_vault_files("nonexistent")
    assert "error" in result


def test_list_vault_files_returns_files(tmp_path):
    vault, executor = make_vault_and_executor(tmp_path)
    (vault.wiki_concepts_dir / "python.md").write_text("python")
    (vault.wiki_concepts_dir / "rust.md").write_text("rust")
    result = executor._list_vault_files("concepts")
    assert set(result["files"]) == {"python.md", "rust.md"}


# ── Agent loop ──────────────────────────────────────────────────────────────

def test_agent_run_end_turn(tmp_path):
    _, executor = make_vault_and_executor(tmp_path)
    executor.client.call_with_tools.return_value = {
        "stop_reason": "end_turn",
        "text": "Goal accomplished.",
        "tool_calls": [],
        "raw_messages": [],
    }
    result = executor.run("Do something.", max_iterations=5)
    assert result == "Goal accomplished."
    executor.client.call_with_tools.assert_called_once()


def test_agent_run_tool_loop_then_end(tmp_path):
    vault, executor = make_vault_and_executor(tmp_path)

    call_count = [0]
    tool_result_messages = [None]

    def fake_call_with_tools(messages, tools, system="", max_tokens=4096):
        call_count[0] += 1
        if call_count[0] == 1:
            return {
                "stop_reason": "tool_use",
                "text": "Let me list files.",
                "tool_calls": [{"name": "list_vault_files", "id": "t1", "input": {"category": "concepts"}}],
                "raw_messages": messages + [{"role": "assistant", "content": []}],
            }
        else:
            return {
                "stop_reason": "end_turn",
                "text": "Done.",
                "tool_calls": [],
                "raw_messages": messages,
            }

    executor.client.call_with_tools.side_effect = fake_call_with_tools
    executor.client.inject_tool_results.side_effect = lambda msgs, tcs, results: msgs

    result = executor.run("List concepts.", max_iterations=5)
    assert result == "Done."
    assert call_count[0] == 2


def test_agent_run_returns_max_iterations_message(tmp_path):
    _, executor = make_vault_and_executor(tmp_path)

    executor.client.call_with_tools.return_value = {
        "stop_reason": "tool_use",
        "text": "",
        "tool_calls": [{"name": "list_vault_files", "id": "t1", "input": {"category": "raw"}}],
        "raw_messages": [{"role": "user", "content": "goal"}],
    }
    executor.client.inject_tool_results.return_value = [{"role": "user", "content": "goal"}]

    result = executor.run("Loop forever.", max_iterations=3)
    assert "Max iterations" in result
    assert executor.client.call_with_tools.call_count == 3
