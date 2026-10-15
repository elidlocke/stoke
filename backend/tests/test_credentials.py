"""Checking, renaming and removing a user's Stripe accounts added with a key, directly and through the API.
Connecting with the Stripe App is in test_stripe_app.py."""

import httpx
import pytest
import respx
from sqlalchemy import select

from app import credentials
from app.auth import current_user
from app.db_models import StripeCredential
from app.main import app
from app.stripe_client import _scope_cache, get_scope
from tests.conftest import add_key, mock_stripe_keys, stripe_account as account

KEY_A = "rk_test_" + "a" * 24 + "A1b2"
KEY_A2 = "rk_test_" + "z" * 24 + "Z9y8"  # a rotated key for the same account
KEY_B = "rk_test_" + "b" * 24 + "B3c4"


@pytest.fixture
def stripe():
    with respx.mock(assert_all_called=False) as mock:
        mock_stripe_keys(mock, {
            KEY_A: account("acct_a", "Creator A", "eur"),
            KEY_A2: account("acct_a", "Creator A", "eur"),
            KEY_B: account("acct_b", "Creator B"),
        }, forbidden={KEY_B: {"Subscriptions"}})
        yield mock


async def test_reverify_marks_a_revoked_key_invalid(db, make_user, stripe):
    user = await make_user()
    async with db() as session:
        cred = await add_key(session, user, KEY_A)
    stripe.routes.clear()
    mock_stripe_keys(stripe, {})  # Stripe now rejects every key

    async with db() as session:
        cred = await credentials.reverify(session, user, cred.id)
    assert cred.status == "invalid"


async def test_changes_refresh_the_users_scope(db, make_user, stripe):
    user = await make_user()
    async with db() as session:
        cred = await add_key(session, user, KEY_A)
        assert [a.id for a in (await get_scope(user)).accounts] == ["acct_a"]

        await add_key(session, user, KEY_B)
        assert str(user.id) not in _scope_cache
        assert [a.id for a in (await get_scope(user)).accounts] == ["acct_a", "acct_b"]

        await credentials.delete(session, user, cred.id)
        assert [a.id for a in (await get_scope(user)).accounts] == ["acct_b"]


# --- Through the API ------------------------------------------------------------------------------


@pytest.fixture
def as_user():
    def sign_in(user):
        app.dependency_overrides[current_user] = lambda: user
    yield sign_in
    app.dependency_overrides.clear()


@pytest.fixture
async def api():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        yield client


async def test_api_never_returns_the_key(db, make_user, stripe, as_user, api):
    user = await make_user()
    as_user(user)
    async with db() as session:
        await add_key(session, user, KEY_A, label="Main")

    resp = await api.get("/api/credentials")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connect_available"] is True
    assert body["credentials"][0]["key_last4"] == "A1b2" and body["credentials"][0]["stripe_account_id"] == "acct_a"
    assert resp.headers["cache-control"] == "no-store"
    assert KEY_A not in resp.text and "a" * 24 not in resp.text and "rk_test" not in resp.text
    assert "ciphertext" not in resp.text and "wrapped_dek" not in resp.text


async def test_keys_cant_be_added_through_the_api(db, make_user, stripe, as_user, api):
    as_user(await make_user())
    assert (await api.post("/api/credentials", json={"key": KEY_A})).status_code == 405
    async with db() as session:
        assert await session.scalar(select(StripeCredential)) is None


async def test_other_users_credentials_are_not_found(db, make_user, stripe, as_user, api):
    owner = await make_user()
    async with db() as session:
        cred_id = (await add_key(session, owner, KEY_A)).id

    as_user(await make_user())
    assert (await api.get("/api/credentials")).json() == {"credentials": [], "connect_available": True}
    assert (await api.patch(f"/api/credentials/{cred_id}", json={"label": "mine"})).status_code == 404
    assert (await api.post(f"/api/credentials/{cred_id}/verify")).status_code == 404
    assert (await api.delete(f"/api/credentials/{cred_id}")).status_code == 404

    async with db() as session:
        assert await session.scalar(select(StripeCredential.label)) is None  # untouched


async def test_rename_verify_delete(db, make_user, stripe, as_user, api):
    user = await make_user()
    as_user(user)
    async with db() as session:
        cred_id = (await add_key(session, user, KEY_A)).id

    assert (await api.patch(f"/api/credentials/{cred_id}", json={"label": "Newsletter"})).json()["label"] == "Newsletter"
    assert (await api.post(f"/api/credentials/{cred_id}/verify")).json()["status"] == "ok"
    assert (await api.delete(f"/api/credentials/{cred_id}")).status_code == 204
    assert (await api.get("/api/credentials")).json() == {"credentials": [], "connect_available": True}


async def test_no_credentials_points_to_settings(db, make_user, as_user, api):
    as_user(await make_user())
    resp = await api.get("/api/accounts")
    assert resp.status_code == 503 and resp.json()["code"] == "no_credentials"


async def test_reporting_currency_setting(db, make_user, stripe, as_user, api):
    user = await make_user()
    as_user(user)
    async with db() as session:
        await add_key(session, user, KEY_A)
    assert (await api.get("/api/accounts")).json()["reporting_currency"] == "eur"

    assert (await api.put("/api/settings", json={"reporting_currency": "CAD"})).json() == {"reporting_currency": "cad"}
    assert (await api.get("/api/accounts")).json()["reporting_currency"] == "cad"
    assert (await api.put("/api/settings", json={"reporting_currency": "dollars"})).status_code == 422
