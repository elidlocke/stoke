"""Adding, rotating, checking and removing a user's Stripe keys, directly and through the API."""

import httpx
import pytest
import respx
from sqlalchemy import select

from app import credentials, fetch
from app.auth import current_user
from app.crypto import get_cipher
from app.db_models import StripeCredential
from app.main import app
from app.stripe_client import _scope_cache, get_scope
from tests.conftest import mock_stripe_keys, stripe_account as account

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


@pytest.mark.parametrize("key, message", [
    ("pk_test_" + "a" * 24, "publishable key"),
    ("sk_live_" + "a" * 24, "Live secret keys"),
    ("hello", "doesn't look like"),
    ("rk_test_short", "doesn't look like"),
])
def test_unusable_formats_are_rejected_without_calling_stripe(key, message):
    with pytest.raises(credentials.CredentialError, match=message):
        credentials.check_format(key)


def test_accepted_formats():
    assert credentials.check_format("rk_live_" + "a" * 24) == ("restricted", True)
    assert credentials.check_format("sk_test_" + "a" * 24) == ("secret", False)


async def test_add_stores_only_ciphertext(db, make_user, stripe):
    user = await make_user()
    async with db() as session:
        cred = await credentials.add(session, user, f"  {KEY_B}\n", label="Side project")

    async with db() as session:
        stored = await session.scalar(select(StripeCredential))
    assert (stored.stripe_account_id, stored.display_name, stored.label) == ("acct_b", "Creator B", "Side project")
    assert (stored.key_type, stored.livemode, stored.key_last4) == ("restricted", False, "B3c4")
    assert stored.status == "missing_permissions" and stored.missing_permissions == ["Subscriptions"]
    assert KEY_B.encode() not in stored.ciphertext + stored.wrapped_dek
    assert await get_cipher().decrypt(stored.sealed, stored.aad) == KEY_B
    assert stored.id == cred.id


async def test_key_stripe_rejects_is_not_stored(db, make_user, stripe):
    user = await make_user()
    async with db() as session:
        with pytest.raises(credentials.InvalidKey):
            await credentials.add(session, user, "rk_test_" + "n" * 24)
        assert await session.scalar(select(StripeCredential)) is None


async def test_same_account_twice_is_rejected(db, make_user, stripe):
    user, other = await make_user(), await make_user()
    async with db() as session:
        await credentials.add(session, user, KEY_A)
        with pytest.raises(credentials.DuplicateAccount, match="Replace key"):
            await credentials.add(session, user, KEY_A2)
        # Another user can add the same account with their own key.
        await credentials.add(session, other, KEY_A2)


async def test_replace_key_rotates_and_must_be_the_same_account(db, make_user, stripe):
    user = await make_user()
    async with db() as session:
        cred = await credentials.add(session, user, KEY_A)
        old_ciphertext = cred.ciphertext
        fetch._cache()[f"acct_a:{cred.id}"] = "stale"

        with pytest.raises(credentials.CredentialError, match="different Stripe account"):
            await credentials.replace_key(session, user, cred.id, KEY_B)

        cred = await credentials.replace_key(session, user, cred.id, KEY_A2)
    assert cred.key_last4 == "Z9y8" and cred.ciphertext != old_ciphertext
    assert await get_cipher().decrypt(cred.sealed, cred.aad) == KEY_A2
    assert f"acct_a:{cred.id}" not in fetch._cache()  # nothing read with the old key is served


async def test_reverify_marks_a_revoked_key_invalid(db, make_user, stripe):
    user = await make_user()
    async with db() as session:
        cred = await credentials.add(session, user, KEY_A)
    stripe.routes.clear()
    mock_stripe_keys(stripe, {})  # Stripe now rejects every key

    async with db() as session:
        cred = await credentials.reverify(session, user, cred.id)
    assert cred.status == "invalid"


async def test_changes_refresh_the_users_scope(db, make_user, stripe):
    user = await make_user()
    async with db() as session:
        cred = await credentials.add(session, user, KEY_A)
        assert [a.id for a in (await get_scope(user)).accounts] == ["acct_a"]

        await credentials.add(session, user, KEY_B)
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
    as_user(await make_user())

    resp = await api.post("/api/credentials", json={"key": KEY_A, "label": "Main"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["key_last4"] == "A1b2" and body["stripe_account_id"] == "acct_a"
    assert resp.headers["cache-control"] == "no-store"

    listed = await api.get("/api/credentials")
    for text in [resp.text, listed.text]:
        assert KEY_A not in text and "a" * 24 not in text and "rk_test" not in text
        assert "ciphertext" not in text and "wrapped_dek" not in text


async def test_invalid_request_does_not_echo_the_key(db, make_user, stripe, as_user, api):
    as_user(await make_user())
    resp = await api.post("/api/credentials", json={"key": KEY_A, "unexpected": True})
    assert resp.status_code == 422
    assert KEY_A not in resp.text

    resp = await api.post("/api/credentials", json={"key": "pk_test_" + "a" * 24})
    assert resp.status_code == 400 and "a" * 24 not in resp.text


async def test_api_errors(db, make_user, stripe, as_user, api):
    as_user(await make_user())
    assert (await api.post("/api/credentials", json={"key": KEY_A})).status_code == 201
    assert (await api.post("/api/credentials", json={"key": KEY_A2})).status_code == 409
    assert (await api.post("/api/credentials", json={"key": "rk_test_" + "n" * 24})).status_code == 400


async def test_other_users_credentials_are_not_found(db, make_user, stripe, as_user, api):
    as_user(await make_user())
    cred_id = (await api.post("/api/credentials", json={"key": KEY_A})).json()["id"]

    as_user(await make_user())
    assert (await api.get("/api/credentials")).json() == {"credentials": []}
    assert (await api.patch(f"/api/credentials/{cred_id}", json={"label": "mine"})).status_code == 404
    assert (await api.put(f"/api/credentials/{cred_id}/key", json={"key": KEY_A2})).status_code == 404
    assert (await api.post(f"/api/credentials/{cred_id}/verify")).status_code == 404
    assert (await api.delete(f"/api/credentials/{cred_id}")).status_code == 404

    async with db() as session:
        assert await session.scalar(select(StripeCredential.label)) is None  # untouched


async def test_rename_verify_delete(db, make_user, stripe, as_user, api):
    as_user(await make_user())
    cred_id = (await api.post("/api/credentials", json={"key": KEY_A})).json()["id"]

    assert (await api.patch(f"/api/credentials/{cred_id}", json={"label": "Newsletter"})).json()["label"] == "Newsletter"
    assert (await api.post(f"/api/credentials/{cred_id}/verify")).json()["status"] == "ok"
    assert (await api.delete(f"/api/credentials/{cred_id}")).status_code == 204
    assert (await api.get("/api/credentials")).json() == {"credentials": []}


async def test_no_credentials_points_to_settings(db, make_user, as_user, api):
    as_user(await make_user())
    resp = await api.get("/api/accounts")
    assert resp.status_code == 503 and resp.json()["code"] == "no_credentials"


async def test_reporting_currency_setting(db, make_user, stripe, as_user, api):
    as_user(await make_user())
    await api.post("/api/credentials", json={"key": KEY_A})
    assert (await api.get("/api/accounts")).json()["reporting_currency"] == "eur"

    assert (await api.put("/api/settings", json={"reporting_currency": "CAD"})).json() == {"reporting_currency": "cad"}
    assert (await api.get("/api/accounts")).json()["reporting_currency"] == "cad"
    assert (await api.put("/api/settings", json={"reporting_currency": "dollars"})).status_code == 422
