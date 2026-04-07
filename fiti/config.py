import json
from pathlib import Path
from typing import Any

_DEFAULTS: dict[str, Any] = {
    "gemini_model": "gemini-2.5-flash",
    "anthropic_model": "claude-3-5-sonnet-20241022",
    "timeout": 30,
    "max_ingest_bytes": 10 * 1024 * 1024,   # 10 MB
    "max_tokens_compile": 1024,
    "max_tokens_query": 2048,
    "max_agent_steps": 10,
    "retry_attempts": 3,
}


class FitiConfig:
    """
    Loads configuration from ~/.fiti/config.json, falling back to defaults.

    Example config.json:
        {
            "anthropic_model": "claude-opus-4-6",
            "timeout": 60,
            "retry_attempts": 5
        }

    Unknown keys are silently ignored.
    """

    def __init__(self, config_dir: Path | None = None):
        self._data: dict[str, Any] = dict(_DEFAULTS)
        cfg_file = (config_dir or Path.home() / ".fiti") / "config.json"
        if cfg_file.exists():
            try:
                with open(cfg_file) as f:
                    overrides = json.load(f)
                for k, v in overrides.items():
                    if k in _DEFAULTS:
                        self._data[k] = v
            except (json.JSONDecodeError, OSError):
                pass  # Silently use defaults on bad config file

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(f"Unknown config key: {name!r}")

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


_instance: FitiConfig | None = None


def get_config() -> FitiConfig:
    global _instance
    if _instance is None:
        _instance = FitiConfig()
    return _instance


def reset_config() -> None:
    """Force reload on next get_config() call. Useful in tests."""
    global _instance
    _instance = None
