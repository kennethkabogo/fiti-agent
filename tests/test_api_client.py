import json
import socket
import urllib.error
import pytest
from unittest.mock import patch, MagicMock

from fiti.api_client import APIClient


def make_client(gemini_key="gkey", anthropic_key=None):
    env = {}
    if gemini_key:
        env["GEMINI_API_KEY"] = gemini_key
    if anthropic_key:
        env["ANTHROPIC_API_KEY"] = anthropic_key
    with patch.dict("os.environ", env, clear=True):
        return APIClient()


def _mock_urlopen(response_body: dict):
    def fake_urlopen(req, timeout=None):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(response_body).encode()
        return mock_resp
    return fake_urlopen


# ── Existing tests ──────────────────────────────────────────────────────────

def test_raises_when_no_keys():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="API Key required"):
            APIClient()


def test_gemini_key_sent_as_header_not_url():
    client = make_client(gemini_key="secret-key")
    captured = []

    def fake_urlopen(req, timeout=None):
        captured.append(req)
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "hello"}]}}]
        }).encode()
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = client.call_gemini("test prompt")

    assert result == "hello"
    req = captured[0]
    assert "secret-key" not in req.full_url
    assert req.get_header("X-goog-api-key") == "secret-key"


def test_gemini_http_error_raises_runtime_error():
    client = make_client(gemini_key="key")
    err = urllib.error.HTTPError(url="", code=401, msg="Unauthorized", hdrs={}, fp=None)
    err.read = lambda: b"bad key"
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(RuntimeError, match="Gemini API error"):
            client.call_gemini("prompt")


def test_gemini_url_error_raises_runtime_error():
    client = make_client(gemini_key="key")
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route")):
        with pytest.raises(RuntimeError, match="Network error reaching Gemini"):
            client.call_gemini("prompt")


def test_gemini_timeout_raises_runtime_error():
    client = make_client(gemini_key="key")
    with patch("urllib.request.urlopen", side_effect=socket.timeout()):
        with pytest.raises(RuntimeError, match="timed out"):
            client.call_gemini("prompt")


def test_anthropic_call_uses_correct_headers():
    client = make_client(gemini_key=None, anthropic_key="ant-key")
    captured = []

    def fake_urlopen(req, timeout=None):
        captured.append(req)
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({"content": [{"text": "world"}]}).encode()
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = client.call_anthropic("test")

    assert result == "world"
    assert captured[0].get_header("X-api-key") == "ant-key"


def test_call_prefers_gemini_when_both_keys_set():
    client = make_client(gemini_key="gkey", anthropic_key="akey")
    called = []

    with patch.object(client, "call_gemini", side_effect=lambda p: called.append("gemini") or "ok"):
        with patch.object(client, "call_anthropic", side_effect=lambda p, max_tokens=1024: called.append("anthropic") or "ok"):
            client.call("prompt")

    assert called == ["gemini"]


def test_anthropic_respects_max_tokens():
    client = make_client(gemini_key=None, anthropic_key="ant-key")
    captured_payloads = []

    def fake_urlopen(req, timeout=None):
        captured_payloads.append(json.loads(req.data))
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({"content": [{"text": "ok"}]}).encode()
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client.call_anthropic("prompt", max_tokens=2048)

    assert captured_payloads[0]["max_tokens"] == 2048


# ── New: error body truncation ──────────────────────────────────────────────

def test_gemini_error_body_truncated_to_500_chars():
    client = make_client(gemini_key="key")
    long_body = "x" * 2000
    err = urllib.error.HTTPError(url="", code=500, msg="Error", hdrs={}, fp=None)
    err.read = lambda: long_body.encode()
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(RuntimeError) as exc_info:
            client.call_gemini("prompt")
    # The error message after "Gemini API error: " should be at most 500 chars
    msg = str(exc_info.value).replace("Gemini API error: ", "")
    assert len(msg) <= 500


def test_anthropic_error_body_truncated_to_500_chars():
    client = make_client(gemini_key=None, anthropic_key="key")
    long_body = "y" * 2000
    err = urllib.error.HTTPError(url="", code=500, msg="Error", hdrs={}, fp=None)
    err.read = lambda: long_body.encode()
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(RuntimeError) as exc_info:
            client.call_anthropic("prompt")
    msg = str(exc_info.value).replace("Anthropic API error: ", "")
    assert len(msg) <= 500


# ── New: call_with_tools (Anthropic) ────────────────────────────────────────

_SAMPLE_TOOLS = [
    {
        "name": "echo",
        "description": "Echo back the input.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    }
]


def test_call_with_tools_anthropic_end_turn():
    client = make_client(gemini_key=None, anthropic_key="key")
    body = {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "All done."}],
    }
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen(body)):
        result = client.call_with_tools(
            [{"role": "user", "content": "hello"}],
            _SAMPLE_TOOLS,
        )
    assert result["stop_reason"] == "end_turn"
    assert result["text"] == "All done."
    assert result["tool_calls"] == []


def test_call_with_tools_anthropic_tool_use():
    client = make_client(gemini_key=None, anthropic_key="key")
    body = {
        "stop_reason": "tool_use",
        "content": [
            {"type": "text", "text": "Let me call echo."},
            {"type": "tool_use", "id": "toolu_1", "name": "echo", "input": {"text": "hi"}},
        ],
    }
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen(body)):
        result = client.call_with_tools(
            [{"role": "user", "content": "hello"}],
            _SAMPLE_TOOLS,
        )
    assert result["stop_reason"] == "tool_use"
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["name"] == "echo"
    assert result["tool_calls"][0]["input"] == {"text": "hi"}
    assert result["tool_calls"][0]["id"] == "toolu_1"


def test_call_with_tools_anthropic_payload_includes_tools():
    """Verify the request payload sent to Anthropic includes tools array."""
    client = make_client(gemini_key=None, anthropic_key="key")
    captured = []

    def fake_urlopen(req, timeout=None):
        captured.append(json.loads(req.data))
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "ok"}],
        }).encode()
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client.call_with_tools([{"role": "user", "content": "hi"}], _SAMPLE_TOOLS)

    payload = captured[0]
    assert "tools" in payload
    assert payload["tools"][0]["name"] == "echo"
    assert "input_schema" in payload["tools"][0]


# ── New: call_with_tools (Gemini) ───────────────────────────────────────────

def test_call_with_tools_gemini_end_turn():
    client = make_client(gemini_key="gkey")
    body = {
        "candidates": [{"content": {"parts": [{"text": "Done."}]}}]
    }
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen(body)):
        result = client.call_with_tools(
            [{"role": "user", "content": "hello"}],
            _SAMPLE_TOOLS,
        )
    assert result["stop_reason"] == "end_turn"
    assert "Done." in result["text"]
    assert result["tool_calls"] == []


def test_call_with_tools_gemini_function_call():
    client = make_client(gemini_key="gkey")
    body = {
        "candidates": [{
            "content": {
                "parts": [{"functionCall": {"name": "echo", "args": {"text": "hi"}}}]
            }
        }]
    }
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen(body)):
        result = client.call_with_tools(
            [{"role": "user", "content": "hello"}],
            _SAMPLE_TOOLS,
        )
    assert result["stop_reason"] == "tool_use"
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["name"] == "echo"
    assert result["tool_calls"][0]["input"] == {"text": "hi"}


def test_call_with_tools_gemini_payload_includes_function_declarations():
    client = make_client(gemini_key="gkey")
    captured = []

    def fake_urlopen(req, timeout=None):
        captured.append(json.loads(req.data))
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
        }).encode()
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client.call_with_tools([{"role": "user", "content": "hi"}], _SAMPLE_TOOLS)

    payload = captured[0]
    assert "tools" in payload
    assert "function_declarations" in payload["tools"][0]
    assert payload["tools"][0]["function_declarations"][0]["name"] == "echo"
