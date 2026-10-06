"""Account discovery: each user's stored keys, plus a platform key in local development."""

import httpx
import pytest
import respx
from sqlalchemy import update

from app import credentials
from app.config import get_settings
from app.db_models import StripeCredential, UserSettings
from app.stripe_client import NoCredentials, get_scope
from tests.conftest import mock_stripe_keys, stripe_account as account


@pytest.fixture
def stripe():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


async def test_own_keys(db, make_user, stripe):
    mock_stripe_keys(stripe, {
        "rk_test_aaaaaaaaaaaa": account("acct_a", "Creator A", "eur"),
        "rk_test_bbbbbbbbbbbb": account("acct_b", "Creator B", "gbp"),
    })
    user = await make_user()
    async with db() as session:
        await credentials.add(session, user, "rk_test_aaaaaaaaaaaa")
        await credentials.add(session, user, "rk_test_bbbbbbbbbbbb", label="My newsletter")

    scope = await get_scope(user)

    assert [(a.id, a.display_name, a.access) for a in scope.accounts] == [
        ("acct_a", "Creator A", "own_key"),
        ("acct_b", "My newsletter", "own_key"),  # the user's label wins
    ]
    assert scope.reporting_currency == "eur"  # the first account's payout currency


async def test_users_only_see_their_own_accounts(db, make_user, stripe):
    mock_stripe_keys(stripe, {
        "rk_test_aaaaaaaaaaaa": account("acct_a", "A"),
        "rk_test_bbbbbbbbbbbb": account("acct_b", "B"),
    })
    alice, bob = await make_user(), await make_user()
    async with db() as session:
        await credentials.add(session, alice, "rk_test_aaaaaaaaaaaa")
        await credentials.add(session, bob, "rk_test_bbbbbbbbbbbb")

    assert [a.id for a in (await get_scope(alice)).accounts] == ["acct_a"]
    assert [a.id for a in (await get_scope(bob)).accounts] == ["acct_b"]


async def test_reporting_currency_preference(db, make_user, stripe):
    mock_stripe_keys(stripe, {"rk_test_aaaaaaaaaaaa": account("acct_a", "A", "eur")})
    user = await make_user()
    async with db() as session:
        await credentials.add(session, user, "rk_test_aaaaaaaaaaaa")
        session.add(UserSettings(user_id=user.id, reporting_currency="cad"))
        await session.commit()

    assert (await get_scope(user)).reporting_currency == "cad"


async def test_key_without_account_read_permission(db, make_user, stripe):
    mock_stripe_keys(stripe, {"rk_test_aaaaaaaaaaaa": None}, balance_currency={"rk_test_aaaaaaaaaaaa": "cad"})
    user = await make_user()
    async with db() as session:
        cred = await credentials.add(session, user, "rk_test_aaaaaaaaaaaa")
    assert cred.missing_permissions == ["Accounts"] and cred.status == "missing_permissions"

    [acct] = (await get_scope(user)).accounts
    assert (acct.id, acct.display_name, acct.settlement_currency) == (f"key-{cred.id}", "Stripe account", "cad")


async def test_rejected_keys_are_left_out(db, make_user, stripe):
    mock_stripe_keys(stripe, {"rk_test_aaaaaaaaaaaa": account("acct_a", "A")})
    user = await make_user()
    async with db() as session:
        await credentials.add(session, user, "rk_test_aaaaaaaaaaaa")
        await session.execute(update(StripeCredential).values(status="invalid"))
        await session.commit()

    with pytest.raises(NoCredentials):
        await get_scope(user)


async def test_no_credentials(db, make_user):
    with pytest.raises(NoCredentials):
        await get_scope(await make_user())


async def test_platform_key_ignored_outside_dev_mode(db, make_user, monkeypatch):
    monkeypatch.setenv("STRIPE_PLATFORM_KEY", "sk_test_platform")
    get_settings.cache_clear()
    with pytest.raises(NoCredentials):
        await get_scope(await make_user())


async def test_dev_platform_and_own_keys_combined(db, make_user, stripe, monkeypatch):
    mock_stripe_keys(stripe, {
        "rk_test_aaaaaaaaaaaa": account("acct_a", "Creator A", "eur"),
        "rk_test_cccccccccccc": account("acct_conn", "Also connected"),
        "sk_test_platform": account("acct_platform", "Platform", "gbp"),
    })
    user = await make_user()
    async with db() as session:
        await credentials.add(session, user, "rk_test_aaaaaaaaaaaa")
        await credentials.add(session, user, "rk_test_cccccccccccc")

    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("STRIPE_PLATFORM_KEY", "sk_test_platform")
    get_settings.cache_clear()
    stripe.get("https://api.stripe.com/v1/accounts").mock(return_value=httpx.Response(200, json={
        "object": "list", "url": "/v1/accounts", "has_more": False,
        "data": [account("acct_conn", "Connected"), account("acct_other", "Other")],
    }))

    scope = await get_scope(user)

    assert [(a.id, a.access) for a in scope.accounts] == [
        ("acct_platform", "platform"),
        ("acct_other", "connected"),
        ("acct_a", "own_key"),
        ("acct_conn", "own_key"),  # reachable both ways: read with its own key, once
    ]
    assert scope.reporting_currency == "gbp"  # platform's payout currency
