from pathlib import Path

_profile_cache: dict[str, str] | None = None


class ProfileNotLoadedError(RuntimeError):
    pass


def load_profile(profile_dir: str) -> dict[str, str]:
    global _profile_cache
    if _profile_cache is not None:
        return _profile_cache

    base = Path(profile_dir)
    files = {
        "profile.yml": base / "profile.yml",
        "portals.yml": base / "portals.yml",
        "cv.md": base / "cv.md",
        "_profile.md": base / "_profile.md",
    }

    loaded: dict[str, str] = {}
    for key, file_path in files.items():
        loaded[key] = file_path.read_text(encoding="utf-8")

    _profile_cache = loaded
    return loaded


def get_profile() -> dict[str, str]:
    if _profile_cache is None:
        raise ProfileNotLoadedError(
            "Profile not loaded: check that CAREER_OPS_DIR points to a directory containing "
            "profile.yml, portals.yml, cv.md and _profile.md"
        )
    return _profile_cache


def invalidate_profile_cache() -> None:
    global _profile_cache
    _profile_cache = None
