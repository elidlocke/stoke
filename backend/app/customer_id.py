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
from collections.abc import Iterable

from app.config import get_settings
from app.secret_file import read_or_create

ID_LENGTH = 24  # hex characters: 96 bits


def _key() -> bytes:
    settings = get_settings()
    # An empty value (as in .env.example) means unset: an empty key would make ids guessable.
    if secret := settings.customer_id_secret and settings.customer_id_secret.get_secret_value():
        return secret.encode()
    return read_or_create(settings.customer_id_secret_file).encode()


def customer_id(email: str) -> str:
    return hmac.new(_key(), email.encode(), hashlib.sha256).hexdigest()[:ID_LENGTH]


def resolve(cid: str, emails: Iterable[str | None]) -> str | None:
    """The email among `emails` whose id is `cid`, if any."""
    key = _key()
    for email in set(emails):
        if email and hmac.compare_digest(hmac.new(key, email.encode(), hashlib.sha256).hexdigest()[:ID_LENGTH], cid):
            return email
    return None
