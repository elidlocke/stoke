"""The signed `state` of an OAuth flow Stoke starts (Gmail, the Stripe App), so nothing is stored server-side
while the writer is at the provider.

The state names the signed-in user and expires, and is signed with a key derived from CUSTOMER_ID_SECRET
for its purpose. Its nonce is also set as a short-lived cookie in the writer's browser: the provider's
redirect back carries no bearer token, so the callback trusts the user the state names only when the
browser also has the nonce. A consent link someone else started can't attach your account to theirs.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid

from app import customer_id
from app.auth import CurrentUser

TTL_SECONDS = 600


class InvalidState(Exception):
    """The state wasn't signed by Stoke, or came back to a different browser."""


class ExpiredState(Exception):
    pass


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(purpose: str, payload: str) -> str:
    return b64(hmac.new(customer_id.subkey(purpose), payload.encode(), hashlib.sha256).digest())


def make(purpose: str, user: CurrentUser, now: float | None = None) -> tuple[str, str]:
    """(state, nonce) for a flow `user` starts."""
    nonce = secrets.token_urlsafe(16)
    payload = b64(json.dumps({"u": str(user.id), "n": nonce, "e": int((now or time.time()) + TTL_SECONDS)}).encode())
    return f"{payload}.{_sign(purpose, payload)}", nonce


def check(purpose: str, state: str, browser_nonce: str | None) -> tuple[uuid.UUID, str]:
    """(user id, nonce) for a `state` Stoke signed for `purpose`, that hasn't expired, returning to the browser
    that started it (whose cookie holds `browser_nonce`)."""
    payload, _, sig = state.partition(".")
    if not sig or not hmac.compare_digest(sig, _sign(purpose, payload)):
        raise InvalidState
    data = json.loads(_unb64(payload))
    if not browser_nonce or not hmac.compare_digest(browser_nonce, data["n"]):
        raise InvalidState
    if data["e"] < time.time():
        raise ExpiredState
    return uuid.UUID(data["u"]), data["n"]
