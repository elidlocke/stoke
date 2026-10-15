"""Connecting Stripe accounts by installing the Stripe App, keeping its tokens fresh, and uninstalls, with Stripe mocked."""

import asyncio
import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from sqlalchemy import select

from app import stripe_app
from app.auth import current_user
from app.crypto import get_cipher
from app.db_models import StripeBackfill, StripeCredential
from app.main import app
from app.stripe_client import NoCredentials, get_scope
from tests.conftest import add_key, mock_stripe_keys, stripe_account
from tests.test_sync import SECRET, signed

ACCESS = "sk_test_access_1"  # Stripe's access tokens are used like secret keys
ACCESS_2 = "sk_test_access_2"
KEY = "rk_test_" + "w" * 24 + "W1x2"  # the writer's key from before the app


@pytest.fixture
def stripe():
    """Stripe's OAuth token endpoint (which rolls the refresh token on every refresh) and the writer's account."""
    with respx.mock(assert_all_called=False) as mock:
        mock_stripe_keys(mock, {
            ACCESS: stripe_account("acct_w", "Writer", "cad"),
            ACCESS_2: stripe_account("acct_w", "Writer", "cad"),
            KEY: stripe_account("acct_w", "Writer", "cad"),
        })
        mock.refresh_token = "rt_1"
        mock.refreshes = 0

        def token(request):
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["authorization_code"]:
                return _tokens(ACCESS, mock.refresh_token)
            if form["refresh_token"] != [mock.refresh_token]:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Refresh token expired"})
            mock.refreshes += 1
            mock.refresh_token = f"rt_{mock.refreshes + 1}"
            return _tokens(ACCESS_2, mock.refresh_token)

        mock.token = mock.post(stripe_app.TOKEN_URL).mock(side_effect=token)
        yield mock


def _tokens(access: str, refresh: str) -> httpx.Response:
    return httpx.Response(200, json={
        "access_token": access, "refresh_token": refresh, "livemode": False, "scope": "stripe_apps",
        "stripe_publishable_key": "pk_test_x", "stripe_user_id": "acct_w", "token_type": "bearer",
    })


@pytest.fixture
async def api(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def writer(db, make_user):
    user = await make_user()
    app.dependency_overrides[current_user] = lambda: user
    return user


async def _start(api) -> str:
    """The install link Settings sends the writer to; its state."""
    url = (await api.post("/api/stripe/connect")).json()["url"]
    assert url.startswith("https://marketplace.stripe.com/oauth/v2/chnlink_test/authorize?")
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["ca_stoke"]
    assert q["redirect_uri"] == ["http://localhost:5173/api/stripe/callback"]
    return q["state"][0]


async def _callback(api, **params) -> str:
    """Stripe's redirect back: where the API then sends the browser."""
    resp = await api.get("/api/stripe/callback", params=params)
    assert resp.status_code == 303
    return resp.headers["location"]


async def _connect(api) -> str:
    return await _callback(api, code="ac_123", state=await _start(api))


async def _stored(db) -> list[StripeCredential]:
    async with db() as session:
        return list(await session.scalars(select(StripeCredential)))


async def test_connect_stores_the_refresh_token_encrypted_and_starts_the_import(db, writer, api, stripe):
    assert await _connect(api) == "/settings?stripe=connected#stripe"

    # The code was exchanged with the app's own secret key.
    auth = stripe.token.calls[0].request.headers["Authorization"]
    assert base64.b64decode(auth.removeprefix("Basic ")).decode() == "sk_test_stoke_app:"

    [cred] = await _stored(db)
    assert (cred.user_id, cred.stripe_account_id, cred.display_name, cred.settlement_currency) == (
        writer.id, "acct_w", "Writer", "cad")
    assert (cred.key_type, cred.key_last4, cred.livemode, cred.status) == ("oauth", None, False, "ok")
    assert b"rt_1" not in cred.ciphertext + cred.wrapped_dek
    assert await get_cipher().decrypt(cred.sealed, cred.aad) == "rt_1"
    async with db() as session:
        assert await session.scalar(select(StripeBackfill.state).limit(1)) == "pending"

    listed = await api.get("/api/credentials")
    assert listed.json()["credentials"][0]["key_type"] == "oauth"
    for secret in ("rt_1", ACCESS, "ciphertext"):
        assert secret not in listed.text
    # Reads use the access token from the install, without refreshing it.
    assert [a.id for a in (await get_scope(writer)).accounts] == ["acct_w"]
    assert stripe.refreshes == 0


async def test_the_flow_must_return_to_the_browser_that_started_it(db, writer, api, stripe):
    state = await _start(api)
    tampered = state[:-2] + ("AA" if not state.endswith("AA") else "BB")
    assert await _callback(api, code="ac_123", state=tampered) == "/settings?stripe=invalid#stripe"

    api.cookies.clear()  # someone else's browser following the writer's install link
    assert await _callback(api, code="ac_123", state=state) == "/settings?stripe=invalid#stripe"
    assert not stripe.token.called
    assert await _stored(db) == []


async def test_cancelling_at_stripe(db, writer, api, stripe):
    await _start(api)
    assert await _callback(api, error="access_denied") == "/settings?stripe=denied#stripe"
    assert not stripe.token.called


async def test_a_code_stripe_refuses(db, writer, api, stripe):
    stripe.token.mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    assert await _connect(api) == "/settings?stripe=failed#stripe"
    assert await _stored(db) == []


async def test_not_configured(db, writer, api, monkeypatch):
    monkeypatch.setenv("STRIPE_APP_SECRET_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()
    resp = await api.post("/api/stripe/connect")
    assert resp.status_code == 503
    assert (await api.get("/api/credentials")).json()["connect_available"] is False


async def test_switching_a_key_account_to_the_app_keeps_it(db, writer, api, stripe):
    async with db() as session:
        old = await add_key(session, writer, KEY, label="Main newsletter")

    assert await _connect(api) == "/settings?stripe=connected#stripe"
    [cred] = await _stored(db)
    assert (cred.id, cred.label) == (old.id, "Main newsletter")  # links paid through it still point at it
    assert (cred.key_type, cred.key_last4) == ("oauth", None)
    assert await get_cipher().decrypt(cred.sealed, cred.aad) == "rt_1"


async def test_refreshing_saves_the_rolled_refresh_token_once(db, writer, api, stripe):
    await _connect(api)
    [cred] = await _stored(db)
    stripe_app.clear_cache()  # an hour later

    tokens = await asyncio.gather(*(stripe_app.access_token(cred) for _ in range(3)))
    assert tokens == [ACCESS_2] * 3
    assert stripe.refreshes == 1  # one refresh at a time: a second would use the already-rolled token
    [cred] = await _stored(db)
    assert await get_cipher().decrypt(cred.sealed, cred.aad) == "rt_2"

    stripe_app.clear_cache()
    assert await stripe_app.access_token(cred) == ACCESS_2
    assert stripe.refreshes == 2


async def test_a_refused_refresh_token_disconnects_the_account(db, writer, api, stripe):
    await _connect(api)
    stripe.refresh_token = "rt_elsewhere"  # the app was uninstalled
    stripe_app.clear_cache()

    with pytest.raises(NoCredentials):
        await get_scope(writer, refresh=True)
    [cred] = await _stored(db)
    assert cred.status == "invalid"
    assert (await api.post(f"/api/credentials/{cred.id}/verify")).json()["status"] == "invalid"


def _deauthorized(app_id: str = "ca_stoke", account: str = "acct_w") -> bytes:
    return json.dumps({
        "id": "evt_1", "object": "event", "type": "account.application.deauthorized", "account": account,
        "livemode": False, "created": 1_760_000_000,
        "data": {"object": {"id": app_id, "object": "application", "name": "Stoke"}},
    }).encode()


async def test_uninstalling_the_app_disconnects_the_account(db, writer, api, stripe):
    await _connect(api)
    assert len((await get_scope(writer)).accounts) == 1

    other_app = _deauthorized("ca_someone_else")
    assert (await api.post("/api/stripe/webhook", content=other_app, headers=signed(other_app))).status_code == 200
    assert [c.status for c in await _stored(db)] == ["ok"]
    assert stripe.refreshes == 0  # not even checked

    stripe.refresh_token = "rt_elsewhere"  # uninstalled: Stripe refuses the refresh token
    body = _deauthorized()
    assert (await api.post("/api/stripe/webhook", content=body, headers=signed(body))).status_code == 200
    assert [c.status for c in await _stored(db)] == ["invalid"]
    with pytest.raises(NoCredentials):
        await get_scope(writer)  # not served from the cached scope


async def test_an_uninstall_event_stripe_doesnt_back_is_ignored(db, writer, api, stripe):
    """A correctly signed event isn't taken on trust: someone with the webhook secret can't disconnect a writer."""
    await _connect(api)
    body = _deauthorized()
    assert (await api.post("/api/stripe/webhook", content=body, headers=signed(body))).status_code == 200
    assert stripe.refreshes == 1  # Stripe still issued a token, so the app is installed
    assert [c.status for c in await _stored(db)] == ["ok"]
    assert [a.id for a in (await get_scope(writer, refresh=True)).accounts] == ["acct_w"]


async def test_an_uninstall_check_stripe_cant_answer_is_retried(db, writer, api, stripe):
    await _connect(api)
    stripe.token.mock(return_value=httpx.Response(500, json={"error": {"type": "api_error"}}))
    body = _deauthorized()
    # Not acknowledged, so Stripe sends the event again later.
    assert (await api.post("/api/stripe/webhook", content=body, headers=signed(body))).status_code >= 500
    assert [c.status for c in await _stored(db)] == ["ok"]


async def test_reconnecting_after_an_uninstall(db, writer, api, stripe):
    await _connect(api)
    stripe.refresh_token = "rt_elsewhere"
    body = _deauthorized()
    await api.post("/api/stripe/webhook", content=body, headers=signed(body))
    assert [c.status for c in await _stored(db)] == ["invalid"]

    stripe.refresh_token = "rt_1"
    assert await _connect(api) == "/settings?stripe=connected#stripe"
    assert [c.status for c in await _stored(db)] == ["ok"]
