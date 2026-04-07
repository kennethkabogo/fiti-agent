import re
import sys
import pytest
from pathlib import Path
from unittest.mock import patch


# ── Topic name validation ──────────────────────────────────────────────────

_TOPIC_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


@pytest.mark.parametrize("name", ["python", "my-topic", "topic_1", "RUST", "go-2024"])
def test_valid_topic_names(name):
    assert _TOPIC_RE.match(name) is not None


@pytest.mark.parametrize("name", ["../evil", "a/b", "topic name", "", "hello!", "../../etc"])
def test_invalid_topic_names(name):
    assert _TOPIC_RE.match(name) is None


def test_cmd_new_rejects_invalid_topic(tmp_path, capsys):
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti import cli
        args = type("A", (), {"topic": "../evil"})()
        with pytest.raises(SystemExit) as exc:
            cli.cmd_new(args)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Invalid topic name" in captured.out


def test_cmd_use_rejects_invalid_topic(tmp_path, capsys):
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti import cli
        args = type("A", (), {"topic": "bad topic!"})()
        with pytest.raises(SystemExit) as exc:
            cli.cmd_use(args)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Invalid topic name" in captured.out


# ── Slug generation ─────────────────────────────────────────────────────────

def _make_slug(question: str) -> str:
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', question.lower())[:30].strip('_') or "query"
    return slug


@pytest.mark.parametrize("question,expected", [
    ("What is Python?", "what_is_python"),
    ("hello world", "hello_world"),
    ("!!!???", "query"),           # all punctuation → fallback
    ("", "query"),                 # empty → fallback
    ("a" * 50, "a" * 30),          # truncated to 30 chars
])
def test_slug_generation(question, expected):
    assert _make_slug(question) == expected
