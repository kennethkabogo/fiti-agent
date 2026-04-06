import json
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
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=2)

    def get_active_topic(self) -> Optional[str]:
        return self.load_state().get("active_topic")

    def set_active_topic(self, topic: str):
        state = self.load_state()
        state["active_topic"] = topic
        self.save_state(state)
