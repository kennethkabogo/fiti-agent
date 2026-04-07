import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


def make_state_manager(tmp_dir):
    from fiti.state import StateManager
    with patch.object(Path, "home", return_value=Path(tmp_dir)):
        return StateManager()


def test_get_active_topic_returns_none_when_no_state(tmp_path):
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.state import StateManager
        sm = StateManager()
        assert sm.get_active_topic() is None


def test_set_and_get_active_topic(tmp_path):
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.state import StateManager
        sm = StateManager()
        sm.set_active_topic("python")
        assert sm.get_active_topic() == "python"


def test_set_active_topic_overwrites_previous(tmp_path):
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.state import StateManager
        sm = StateManager()
        sm.set_active_topic("python")
        sm.set_active_topic("rust")
        assert sm.get_active_topic() == "rust"


def test_load_state_recovers_from_corrupt_json(tmp_path):
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.state import StateManager
        sm = StateManager()
        sm.state_file.parent.mkdir(parents=True, exist_ok=True)
        sm.state_file.write_text("{not valid json}")
        assert sm.load_state() == {}


def test_save_state_is_atomic(tmp_path):
    """Verify save uses a temp file then os.replace (no partial writes visible)."""
    with patch.object(Path, "home", return_value=tmp_path):
        from fiti.state import StateManager
        sm = StateManager()

        replaced = []
        original_replace = os.replace

        def tracking_replace(src, dst):
            replaced.append((str(src), str(dst)))
            original_replace(src, dst)

        with patch("os.replace", side_effect=tracking_replace):
            sm.set_active_topic("topics")

        assert len(replaced) == 1
        src, dst = replaced[0]
        assert src.endswith(".tmp")
        assert dst == str(sm.state_file)
        assert json.loads(sm.state_file.read_text())["active_topic"] == "topics"
