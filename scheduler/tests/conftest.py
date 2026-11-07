import os
import sys
from pathlib import Path

os.environ.setdefault("PROJECT_DIR", "/project")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import config  # noqa: E402


@pytest.fixture
def runs_file(tmp_path, monkeypatch):
    path = tmp_path / "scheduler-runs.json"
    monkeypatch.setattr(config, "RUNS_FILE", str(path))
    return path
