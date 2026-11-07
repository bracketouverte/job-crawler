import os
import sys
from pathlib import Path

os.environ.setdefault("NVIDIA_API_KEY", "test-key")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from services import profile as profile_service  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_profile_cache():
    profile_service.invalidate_profile_cache()
    yield
    profile_service.invalidate_profile_cache()


@pytest.fixture
def profile_data():
    return {
        "profile.yml": "name: Test Candidate\nlocation: Cooper City, FL, US",
        "portals.yml": "target_roles:\n  - Technical Program Manager",
        "cv.md": "10+ years of experience in SaaS product management.",
        "_profile.md": "Prefers remote-first roles.",
    }


@pytest.fixture
def profile_dir(tmp_path, profile_data):
    base = tmp_path / "career-ops"
    base.mkdir()
    (base / "profile.yml").write_text(profile_data["profile.yml"], encoding="utf-8")
    (base / "portals.yml").write_text(profile_data["portals.yml"], encoding="utf-8")
    (base / "cv.md").write_text(profile_data["cv.md"], encoding="utf-8")
    (base / "_profile.md").write_text(profile_data["_profile.md"], encoding="utf-8")
    return base
