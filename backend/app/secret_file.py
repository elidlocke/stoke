"""Random secrets generated on first run and kept in a gitignored file next to .env."""

import os
import secrets
from pathlib import Path

_cache: dict[Path, str] = {}


def read_or_create(path: Path) -> str:
    """The 32-byte hex secret in `path`, creating it (mode 0600) if it doesn't exist."""
    if path not in _cache:
        try:
            # O_EXCL: if several workers start at once, exactly one creates the key; the rest read it.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        key = path.read_text().strip()
        if not key:
            raise RuntimeError(f"{path} is empty; delete it to generate a new key")
        _cache[path] = key
    return _cache[path]
