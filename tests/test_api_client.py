import json
import socket
import urllib.error
import pytest
from unittest.mock import patch, MagicMock

from fiti.api_client import APIClient


def make_client(gemini_key="gkey", anthropic_key=None):
    with patch.dict("os.environ", {
        "GEMINI_API_KEY": gemini_key or "",
        "ANTHROPIC_API_KEY": anthropic_key or "",
    }, clear=False):
        env = {}
        if gemini_key:
            env["GEMINI_API_KEY"] = gemini_key
        if anthropic_key:
            env["ANTHROPIC_API_KEY"] = anthropic_key
        with patch.dict("os.environ", env):
            return APIClient()


def test_raises_when_no_keys():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="API Key required"):
            APIClient()


def test_gemini_key_sent_as_header_not_url(tmp_path):
    """Ensure Gemini API key goes in x-goog-api-key header, NOT the URL."""
    client = make_client(gemini_key="secret-key")
    captured_requests = []

    def fake_urlopen(req, timeout=None):
        captured_requests.append(req)
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
    assert len(captured_requests) == 1
    req = captured_requests[0]
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
    captured_requests = []

    def fake_urlopen(req, timeout=None):
        captured_requests.append(req)
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({
            "content": [{"text": "world"}]
        }).encode()
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = client.call_anthropic("test")

    assert result == "world"
    req = captured_requests[0]
    assert req.get_header("X-api-key") == "ant-key"


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
