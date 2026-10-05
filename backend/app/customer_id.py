"""Opaque customer ids for URLs, so links and logs carry neither an email nor a Stripe id.

An id is a keyed hash (HMAC) of the customer's email. A plain hash of an email could be reversed
by hashing guessed addresses; the key prevents that, so it must be secret: not derived from
anything public such as account names or ids. It's also independent of API keys and of which
accounts are connected, so ids (and bookmarked links) survive key rotation and Stripe App installs.

The key is CUSTOMER_ID_SECRET if set, else a random key generated on first run and kept in
CUSTOMER_ID_SECRET_FILE. Losing or changing it changes every id.
"""

import hashlib
import hmac
import os
import secrets
from collections.abc import Iterable
from pathlib import Path

from app.config import get_settings

ID_LENGTH = 24  # hex characters: 96 bits

_file_keys: dict[Path, bytes] = {}


def _file_key(path: Path) -> bytes:
    if path not in _file_keys:
        try:
            # O_EXCL: if several workers start at once, exactly one creates the key; the rest read it.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        key = path.read_text().strip()
        if not key:
            raise RuntimeError(f"{path} is empty; delete it to generate a new customer id key")
        _file_keys[path] = key.encode()
    return _file_keys[path]


def _key() -> bytes:
    settings = get_settings()
    # An empty value (as in .env.example) means unset: an empty key would make ids guessable.
    if secret := settings.customer_id_secret and settings.customer_id_secret.get_secret_value():
        return secret.encode()
    return _file_key(settings.customer_id_secret_file)


def customer_id(email: str) -> str:
    return hmac.new(_key(), email.encode(), hashlib.sha256).hexdigest()[:ID_LENGTH]


def resolve(cid: str, emails: Iterable[str | None]) -> str | None:
    """The email among `emails` whose id is `cid`, if any."""
    key = _key()
    for email in set(emails):
        if email and hmac.compare_digest(hmac.new(key, email.encode(), hashlib.sha256).hexdigest()[:ID_LENGTH], cid):
            return email
    return None
