"""Stoke's Stripe App: how writers connect their Stripe accounts, by installing it with Stripe's OAuth flow.

1. `authorization_url` gives the frontend the app's install link (STRIPE_APP_INSTALL_URL), with a signed
   `state` naming the signed-in user (app/oauth_state.py). Its nonce is set as a cookie (routers/stripe_app.py).
2. The writer picks an account and approves the app's read-only permissions (stripe-app/stripe-app.json), and
   Stripe sends their browser back to GET /api/stripe/callback (Settings.stripe_app_redirect_uri).
3. The code is exchanged for an access token (valid for an hour), a refresh token and the account's id, using
   the app's own Stripe account's secret key (credentials.connect_app stores them).

The refresh token is stored only encrypted, in the credential's ciphertext. Stripe rolls it on every refresh,
so each new one is saved before the access token it came with is used, one refresh at a time per credential.
Access tokens are kept in memory only. If Stripe refuses the refresh token (the app was uninstalled), the
credential is marked invalid and the writer is asked to reconnect.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
import stripe
from sqlalchemy import select, update

from app import oauth_state
from app.auth import CurrentUser
from app.config import get_settings
from app.crypto import get_cipher
from app.db import sessionmaker
from app.db_models import StripeCredential

log = logging.getLogger("stoke.stripe_app")

TOKEN_URL = "https://api.stripe.com/v1/oauth/token"
STATE_PURPOSE = "stripe-app-state"
STATE_TTL_SECONDS = oauth_state.TTL_SECONDS
TIMEOUT = 15
# Stripe's access tokens last an hour. One is used until 10 minutes before then: longer than any Stripe client
# built from it is cached (the 5-minute scope cache, the sync worker's 60-second one).
ACCESS_TOKEN_SECONDS = 3600
ACCESS_TOKEN_MARGIN = 600


class StripeAppError(Exception):
    """The app can't be connected; the message is safe to show the user. `reason` is the code Settings
    explains after Stripe's redirect (only codes travel in that URL, never text)."""

    def __init__(self, message: str, reason: str = "failed"):
        super().__init__(message)
        self.reason = reason


class NotConfigured(StripeAppError):
    pass


class AppDisconnected(Exception):
    """Stripe refused the credential's refresh token: the app was uninstalled. The credential is now invalid."""


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    account_id: str
    livemode: bool


def _config() -> tuple[str, str]:
    s = get_settings()
    secret = s.stripe_app_secret_key.get_secret_value() if s.stripe_app_secret_key else ""
    if not s.stripe_app_install_url or not secret:
        raise NotConfigured(
            "Connecting Stripe isn't set up on this server yet (STRIPE_APP_INSTALL_URL and STRIPE_APP_SECRET_KEY)."
        )
    return s.stripe_app_install_url, secret


def configured() -> bool:
    try:
        _config()
    except NotConfigured:
        return False
    return True


def client_id() -> str | None:
    """The app's id (ca_…), from its install link."""
    found = parse_qs(urlparse(get_settings().stripe_app_install_url).query).get("client_id")
    return found[0] if found else None


# --- Connecting -----------------------------------------------------------------------------------


def authorization_url(user: CurrentUser) -> tuple[str, str]:
    """The app's install link for this writer, and the flow's nonce for the browser's cookie."""
    install_url, _ = _config()
    state, nonce = oauth_state.make(STATE_PURPOSE, user)
    parts = urlparse(install_url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()} | {
        "redirect_uri": get_settings().stripe_app_redirect_uri,
        "state": state,
    }
    return urlunparse(parts._replace(query=urlencode(query))), nonce


def check_state(state: str, browser_nonce: str | None) -> uuid.UUID:
    """The user who started the flow (app/oauth_state.py)."""
    try:
        user_id, _ = oauth_state.check(STATE_PURPOSE, state, browser_nonce)
    except oauth_state.InvalidState:
        raise StripeAppError("That Stripe connection couldn't be checked. Start again from Settings.", "invalid") from None
    except oauth_state.ExpiredState:
        raise StripeAppError("That Stripe connection took too long. Start again from Settings.", "expired") from None
    return user_id


def _error_of(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error")
    except ValueError:
        return "?"
    return err if isinstance(err, str) else (err or {}).get("type", "?")


async def _token_request(data: dict) -> httpx.Response:
    _, secret = _config()
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        return await http.post(TOKEN_URL, data=data, auth=(secret, ""))


async def exchange_code(code: str) -> Tokens:
    """The tokens for the account the writer just installed the app on."""
    resp = await _token_request({"grant_type": "authorization_code", "code": code})
    if resp.status_code != 200:
        log.warning("Stripe App code exchange failed: %s %s", resp.status_code, _error_of(resp))
        raise StripeAppError("Stripe didn't accept that connection. Try connecting again.")
    t = resp.json()
    if not t.get("refresh_token") or not t.get("stripe_user_id"):
        raise StripeAppError("Stripe didn't grant lasting access. Try connecting again.")
    return Tokens(t["access_token"], t["refresh_token"], t["stripe_user_id"], bool(t.get("livemode")))


async def seal(cred: StripeCredential, refresh_token: str) -> None:
    sealed = await get_cipher().encrypt(refresh_token, cred.aad)
    cred.ciphertext, cred.wrapped_dek, cred.cipher = sealed.ciphertext, sealed.wrapped_dek, sealed.cipher


# --- Access tokens --------------------------------------------------------------------------------

# credential id -> (access token, when to stop using it, in time.monotonic())
_access: dict[uuid.UUID, tuple[str, float]] = {}
_locks: dict[uuid.UUID, asyncio.Lock] = {}


def remember(credential_id: uuid.UUID, token: str) -> None:
    _access[credential_id] = (token, time.monotonic() + ACCESS_TOKEN_SECONDS - ACCESS_TOKEN_MARGIN)


def forget(credential_id: uuid.UUID) -> None:
    _access.pop(credential_id, None)


def clear_cache() -> None:
    _access.clear()


def _cached(credential_id: uuid.UUID) -> str | None:
    cached = _access.get(credential_id)
    return cached[0] if cached and cached[1] > time.monotonic() else None


async def access_token(cred: StripeCredential) -> str:
    """A current access token for an app credential, refreshing it (and saving the rolled refresh token) when
    needed. AppDisconnected if Stripe refuses the refresh token; a Stripe connection error if it can't be reached."""
    if (token := _cached(cred.id)) is not None:
        return token
    async with _locks.setdefault(cred.id, asyncio.Lock()):
        if (token := _cached(cred.id)) is not None:  # refreshed while this call waited
            return token
        disconnected = False
        async with sessionmaker()() as session, session.begin():
            row = await session.get(StripeCredential, cred.id, with_for_update=True)
            if row is None or not row.is_app or row.status == "invalid":
                raise AppDisconnected
            refresh = await get_cipher().decrypt(row.sealed, row.aad)
            resp = await _token_request({"grant_type": "refresh_token", "refresh_token": refresh})
            if resp.status_code in (400, 401) and _error_of(resp) in ("invalid_grant", "invalid_request"):
                log.info("Stripe refused a Stripe App refresh token: %s", _error_of(resp))
                row.status, row.missing_permissions = "invalid", []
                disconnected = True
            elif resp.status_code != 200:
                log.warning("Stripe App token refresh failed: %s %s", resp.status_code, _error_of(resp))
                raise stripe.APIConnectionError("Couldn't refresh a Stripe App access token")
            else:
                t = resp.json()
                await seal(row, t["refresh_token"])  # committed with this block, before the access token is used
                token = t["access_token"]
        if disconnected:
            forget(cred.id)
            raise AppDisconnected
        remember(cred.id, token)
        return token


async def uninstalled(account_id: str, livemode: bool) -> list[uuid.UUID]:
    """The app was uninstalled from an account: every app credential for it stops working. The ids of the users
    whose credentials changed."""
    async with sessionmaker()() as session, session.begin():
        rows = list(await session.scalars(select(StripeCredential).where(
            StripeCredential.stripe_account_id == account_id, StripeCredential.livemode == livemode,
            StripeCredential.key_type == "oauth",
        )))
        if rows:
            await session.execute(
                update(StripeCredential).where(StripeCredential.id.in_([r.id for r in rows]))
                .values(status="invalid", missing_permissions=[])
            )
    for r in rows:
        forget(r.id)
    return [r.user_id for r in rows]
