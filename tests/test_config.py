import json
import pytest
from pathlib import Path
from unittest.mock import patch

from fiti.config import FitiConfig, get_config, reset_config


def test_defaults_when_no_file(tmp_path):
    cfg = FitiConfig(config_dir=tmp_path)
    assert cfg.gemini_model == "gemini-2.5-flash"
    assert cfg.anthropic_model == "claude-3-5-sonnet-20241022"
    assert cfg.timeout == 30
    assert cfg.max_ingest_bytes == 10 * 1024 * 1024
    assert cfg.max_tokens_compile == 1024
    assert cfg.max_tokens_query == 2048
    assert cfg.max_agent_steps == 10
    assert cfg.retry_attempts == 3


def test_user_overrides_applied(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "anthropic_model": "claude-opus-4-6",
        "timeout": 60,
        "retry_attempts": 5,
    }))
    cfg = FitiConfig(config_dir=tmp_path)
    assert cfg.anthropic_model == "claude-opus-4-6"
    assert cfg.timeout == 60
    assert cfg.retry_attempts == 5
    # Unchanged defaults still present
    assert cfg.gemini_model == "gemini-2.5-flash"
    assert cfg.max_agent_steps == 10


def test_unknown_keys_are_ignored(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"totally_unknown_key": "value", "timeout": 45}))
    cfg = FitiConfig(config_dir=tmp_path)
    assert cfg.timeout == 45
    with pytest.raises(AttributeError):
        _ = cfg.totally_unknown_key


def test_malformed_json_uses_defaults(tmp_path):
    (tmp_path / "config.json").write_text("{not valid json}")
    cfg = FitiConfig(config_dir=tmp_path)
    assert cfg.timeout == 30  # default


def test_to_dict_returns_all_keys(tmp_path):
    cfg = FitiConfig(config_dir=tmp_path)
    d = cfg.to_dict()
    assert "gemini_model" in d
    assert "retry_attempts" in d
    assert len(d) == 8


def test_get_config_cached(tmp_path):
    reset_config()
    with patch.object(Path, "home", return_value=tmp_path):
        c1 = get_config()
        c2 = get_config()
    assert c1 is c2


def test_reset_config_forces_reload(tmp_path):
    reset_config()
    with patch.object(Path, "home", return_value=tmp_path):
        c1 = get_config()
        reset_config()
        c2 = get_config()
    assert c1 is not c2
