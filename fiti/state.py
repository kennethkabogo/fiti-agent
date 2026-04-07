import json
import os
import tempfile
from pathlib import Path
from typing import Optional


class StateManager:
    def __init__(self):
        self.config_dir = Path.home() / ".fiti"
        self.state_file = self.config_dir / "state.json"
        self._ensure_dir()

    def _ensure_dir(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def load_state(self) -> dict:
        if not self.state_file.exists():
            return {}
        try:
            with open(self.state_file, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}

    def save_state(self, state: dict):
        fd, tmp = tempfile.mkstemp(dir=self.config_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.state_file)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def get_active_topic(self) -> Optional[str]:
        return self.load_state().get("active_topic")

    def set_active_topic(self, topic: str):
        state = self.load_state()
        state["active_topic"] = topic
        self.save_state(state)
