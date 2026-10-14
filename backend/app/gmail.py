"""Sending notes from the writer's own Gmail, with the gmail.send scope only.

Connecting is Google's OAuth authorization-code flow with PKCE:
1. `authorization_url` gives the frontend Google's consent page, with a `state` that names the signed-in
   user and expires, signed with a key derived from CUSTOMER_ID_SECRET. The PKCE verifier is derived from
   the state's nonce, so nothing is stored server-side while the writer is at Google. The nonce is also set
   as a short-lived cookie in the writer's browser (routers/gmail.py).
2. Google sends the writer's browser back to the API's GET /api/gmail/callback (Settings.gmail_redirect_uri),
   which then redirects to Settings. Google's code never reaches the frontend's URL, where the Auth0 SDK
   would take it for its own sign-in, and connecting doesn't depend on the Auth0 session surviving the trip.
   The redirect carries no bearer token, so `connect` trusts the user the signed state names only when the
   browser also has the nonce cookie: a consent link someone else started can't attach your Gmail to their
   account.
3. The code is exchanged for a refresh token, stored only encrypted (app/crypto.py), and the Gmail address
   from the ID token (the `openid email` scopes, which aren't sensitive).

Access tokens are kept in memory for under an hour. If Google refuses the refresh token (the writer
revoked access, or, while the Google app is in Testing, after 7 days), the connection is marked revoked
and the writer is asked to reconnect.

Notes are sent as plain-text RFC 822 messages through users.messages.send. They land in the writer's
Sent folder, and replies go to them. Stoke never reads their mail.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.policy import SMTP
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app import customer_id
from app.auth import CurrentUser
from app.config import get_settings
from app.crypto import get_cipher
from app.db_models import GmailConnection

log = logging.getLogger("stoke.gmail")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
SCOPES = ["openid", "email", SEND_SCOPE]
STATE_TTL_SECONDS = 600
TIMEOUT = 15


class GmailError(Exception):
    """Gmail can't be connected or used; the message is safe to show the user. `reason` says why a connection
    failed, for Settings to explain after Google's redirect (only codes travel in that URL, never text)."""

    def __init__(self, message: str, reason: str = "failed"):
        super().__init__(message)
        self.reason = reason


class NotConfigured(GmailError):
    pass


class NotConnected(GmailError):
    pass


@dataclass(frozen=True)
class Sent:
    message_id: str
    thread_id: str


def _client() -> tuple[str, str]:
    s = get_settings()
    secret = s.google_client_secret.get_secret_value() if s.google_client_secret else ""
    if not s.google_client_id or not secret:
        raise NotConfigured("Gmail sending isn't set up on this server yet (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET).")
    return s.google_client_id, secret


def configured() -> bool:
    try:
        _client()
    except NotConfigured:
        return False
    return True


# --- Connecting -----------------------------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str) -> str:
    return _b64(hmac.new(customer_id.subkey("gmail-oauth-state"), payload.encode(), hashlib.sha256).digest())


def _verifier(nonce: str) -> str:
    """The PKCE code verifier for a flow, derived from its state's nonce (43 characters, as PKCE needs)."""
    return _b64(hmac.new(customer_id.subkey("gmail-pkce"), nonce.encode(), hashlib.sha256).digest())


def _state(user: CurrentUser, now: float | None = None) -> tuple[str, str]:
    nonce = secrets.token_urlsafe(16)
    payload = _b64(json.dumps({"u": str(user.id), "n": nonce, "e": int((now or time.time()) + STATE_TTL_SECONDS)}).encode())
    return f"{payload}.{_sign(payload)}", nonce


def check_state(state: str, browser_nonce: str | None) -> tuple[uuid.UUID, str]:
    """(user id, nonce) for a `state` Stoke signed, that hasn't expired, returning to the browser that started it
    (whose cookie holds `browser_nonce`)."""
    invalid = GmailError("That Gmail sign-in couldn't be checked. Start again from Settings.", "invalid")
    payload, _, sig = state.partition(".")
    if not sig or not hmac.compare_digest(sig, _sign(payload)):
        raise invalid
    data = json.loads(_unb64(payload))
    if not browser_nonce or not hmac.compare_digest(browser_nonce, data["n"]):
        raise invalid
    if data["e"] < time.time():
        raise GmailError("That Gmail sign-in took too long. Start again from Settings.", "expired")
    return uuid.UUID(data["u"]), data["n"]


def authorization_url(user: CurrentUser) -> tuple[str, str]:
    """Google's consent page, and the flow's nonce for the browser's cookie."""
    client_id, _ = _client()
    state, nonce = _state(user)
    challenge = _b64(hashlib.sha256(_verifier(nonce).encode()).digest())
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id,
        "redirect_uri": get_settings().gmail_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",  # a refresh token, to send later
        "prompt": "consent",  # every time, so Google returns a refresh token even on a reconnect
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }), nonce


async def connect(session: AsyncSession, code: str, state: str, browser_nonce: str | None) -> GmailConnection:
    """Finishes the flow `authorization_url` started: stores the refresh token and the Gmail address for the
    user who started it."""
    client_id, client_secret = _client()
    user_id, nonce = check_state(state, browser_nonce)
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        resp = await http.post(TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": get_settings().gmail_redirect_uri,
            "client_id": client_id, "client_secret": client_secret, "code_verifier": _verifier(nonce),
        })
    if resp.status_code != 200:
        log.warning("Gmail code exchange failed: %s %s", resp.status_code, _error_of(resp))
        raise GmailError("Google didn't accept that sign-in. Try connecting again.")
    tokens = resp.json()
    if SEND_SCOPE not in tokens.get("scope", "").split():
        log.warning("Gmail connected without the send permission; granted: %s", tokens.get("scope"))
        raise GmailError("Stoke needs permission to send email.", "no_permission")
    if not tokens.get("refresh_token"):
        raise GmailError("Google didn't grant lasting access. Try connecting again.")
    # Straight from Google's token endpoint over TLS, so the ID token needn't be signature-checked
    # (OpenID Connect Core 3.1.3.7); its audience still must be us.
    claims = jwt.decode(tokens.get("id_token", ""), options={"verify_signature": False})
    if claims.get("aud") != client_id or not claims.get("email") or not claims.get("email_verified"):
        raise GmailError("Google didn't say which Gmail address this is. Try connecting again.")

    conn = await session.get(GmailConnection, user_id)
    if conn is None:
        conn = GmailConnection(user_id=user_id)
        session.add(conn)
    sealed = await get_cipher().encrypt(tokens["refresh_token"], conn.aad)
    conn.ciphertext, conn.wrapped_dek, conn.cipher = sealed.ciphertext, sealed.wrapped_dek, sealed.cipher
    conn.email, conn.status = claims["email"].lower(), "ok"
    await session.commit()
    _remember(user_id, tokens.get("access_token"), tokens.get("expires_in"))
    return conn


async def connection(session: AsyncSession, user: CurrentUser) -> GmailConnection | None:
    return await session.get(GmailConnection, user.id)


async def disconnect(session: AsyncSession, user: CurrentUser) -> None:
    """Revokes Stoke's access at Google (best effort) and forgets the token."""
    conn = await session.get(GmailConnection, user.id)
    if conn is None:
        return
    _access.pop(user.id, None)
    try:
        token = await get_cipher().decrypt(conn.sealed, conn.aad)
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            await http.post(REVOKE_URL, data={"token": token})
    except Exception as exc:  # already revoked, or Google unreachable: forgetting the token still disconnects
        log.info("Couldn't revoke a Gmail token: %s", type(exc).__name__)
    await session.delete(conn)
    await session.commit()


# --- Sending --------------------------------------------------------------------------------------

# user id -> (access token, when it expires, in time.monotonic())
_access: dict[uuid.UUID, tuple[str, float]] = {}


def _remember(user_id: uuid.UUID, token: str | None, expires_in: int | None) -> None:
    if token:
        _access[user_id] = (token, time.monotonic() + max(0, (expires_in or 3600) - 120))


def clear_cache() -> None:
    _access.clear()


def _error_of(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error")
    except ValueError:
        return "?"
    return err if isinstance(err, str) else (err or {}).get("status", "?")


async def _revoked(session: AsyncSession, conn: GmailConnection) -> GmailError:
    conn.status = "revoked"
    _access.pop(conn.user_id, None)
    await session.commit()
    return GmailError("Google no longer lets Stoke send from your Gmail. Reconnect Gmail in Settings.")


async def _access_token(session: AsyncSession, conn: GmailConnection) -> str:
    cached = _access.get(conn.user_id)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    client_id, client_secret = _client()
    refresh = await get_cipher().decrypt(conn.sealed, conn.aad)
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        resp = await http.post(TOKEN_URL, data={
            "grant_type": "refresh_token", "refresh_token": refresh, "client_id": client_id, "client_secret": client_secret,
        })
    if resp.status_code == 400 and _error_of(resp) == "invalid_grant":
        raise await _revoked(session, conn)
    if resp.status_code != 200:
        log.warning("Gmail token refresh failed: %s %s", resp.status_code, _error_of(resp))
        raise GmailError("Couldn't reach Gmail. Try again in a minute.")
    tokens = resp.json()
    _remember(conn.user_id, tokens["access_token"], tokens.get("expires_in"))
    return tokens["access_token"]


def message(to: str, subject: str, body: str) -> str:
    """A plain-text message, base64url-encoded as users.messages.send takes it. Gmail adds From (the
    writer's address and name), Date and Message-ID."""
    msg = EmailMessage(policy=SMTP)
    try:
        msg["To"] = to
    except (ValueError, IndexError) as exc:
        raise GmailError("That email address can't be sent to.") from exc
    msg["Subject"] = " ".join(subject.split())  # one line: no header injection
    msg.set_content(body)
    return _b64(msg.as_bytes())


async def send(session: AsyncSession, user: CurrentUser, to: str, subject: str, body: str) -> Sent:
    """Sends a note from the writer's Gmail."""
    conn = await session.get(GmailConnection, user.id)
    if conn is None:
        raise NotConnected("Connect your Gmail in Settings to send from Stoke.")
    if conn.status != "ok":
        raise NotConnected("Reconnect your Gmail in Settings to send from Stoke.")
    raw = message(to, subject, body)
    for attempt in range(2):
        token = await _access_token(session, conn)
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            resp = await http.post(SEND_URL, json={"raw": raw}, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 401 and attempt == 0:  # the cached access token was revoked early: refresh once
            _access.pop(user.id, None)
            continue
        break
    if resp.status_code in (401, 403) and _error_of(resp) in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
        raise await _revoked(session, conn)
    if resp.status_code != 200:
        log.warning("Gmail send failed: %s %s", resp.status_code, _error_of(resp))
        if resp.status_code == 429:
            raise GmailError("Gmail's sending limit was reached. Try again later.")
        raise GmailError("Gmail didn't send the note. Try again in a minute.")
    data = resp.json()
    conn.last_sent_at = datetime.now(UTC)
    await session.commit()
    return Sent(message_id=data["id"], thread_id=data.get("threadId", data["id"]))
