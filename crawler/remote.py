import re

_REMOTE_WORD_RE = re.compile(r"\bremote\b", re.IGNORECASE)


def is_remote_location(location: str | None) -> int | None:
    """1 when the location names remote work, 0 when it names a place without
    remote, None when there is no location to judge."""
    if not location or not location.strip():
        return None
    return 1 if _REMOTE_WORD_RE.search(location) else 0
