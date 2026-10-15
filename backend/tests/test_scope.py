"""Account discovery: each user's stored keys, plus a platform key in local development."""

import pytest
import respx
from sqlalchemy import update

from app.db_models import StripeCredential, UserSettings
from app.stripe_client import NoCredentials, get_scope
from tests.conftest import add_key, mock_stripe_keys, stripe_account as account


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
        await add_key(session, user, "rk_test_aaaaaaaaaaaa")
        await add_key(session, user, "rk_test_bbbbbbbbbbbb", label="My newsletter")

    scope = await get_scope(user)

    assert [(a.id, a.display_name) for a in scope.accounts] == [
        ("acct_a", "Creator A"),
        ("acct_b", "My newsletter"),  # the user's label wins
    ]
    assert scope.reporting_currency == "eur"  # the first account's payout currency


async def test_users_only_see_their_own_accounts(db, make_user, stripe):
    mock_stripe_keys(stripe, {
        "rk_test_aaaaaaaaaaaa": account("acct_a", "A"),
        "rk_test_bbbbbbbbbbbb": account("acct_b", "B"),
    })
    alice, bob = await make_user(), await make_user()
    async with db() as session:
        await add_key(session, alice, "rk_test_aaaaaaaaaaaa")
        await add_key(session, bob, "rk_test_bbbbbbbbbbbb")

    assert [a.id for a in (await get_scope(alice)).accounts] == ["acct_a"]
    assert [a.id for a in (await get_scope(bob)).accounts] == ["acct_b"]


async def test_reporting_currency_preference(db, make_user, stripe):
    mock_stripe_keys(stripe, {"rk_test_aaaaaaaaaaaa": account("acct_a", "A", "eur")})
    user = await make_user()
    async with db() as session:
        await add_key(session, user, "rk_test_aaaaaaaaaaaa")
        session.add(UserSettings(user_id=user.id, reporting_currency="cad"))
        await session.commit()

    assert (await get_scope(user)).reporting_currency == "cad"


async def test_key_without_account_read_permission(db, make_user, stripe):
    mock_stripe_keys(stripe, {"rk_test_aaaaaaaaaaaa": None}, balance_currency={"rk_test_aaaaaaaaaaaa": "cad"})
    user = await make_user()
    async with db() as session:
        cred = await add_key(session, user, "rk_test_aaaaaaaaaaaa")
    assert cred.missing_permissions == ["Accounts"] and cred.status == "missing_permissions"

    [acct] = (await get_scope(user)).accounts
    assert (acct.id, acct.display_name, acct.settlement_currency) == (f"key-{cred.id}", "Stripe account", "cad")


async def test_rejected_keys_are_left_out(db, make_user, stripe):
    mock_stripe_keys(stripe, {"rk_test_aaaaaaaaaaaa": account("acct_a", "A")})
    user = await make_user()
    async with db() as session:
        await add_key(session, user, "rk_test_aaaaaaaaaaaa")
        await session.execute(update(StripeCredential).values(status="invalid"))
        await session.commit()

    with pytest.raises(NoCredentials):
        await get_scope(user)


async def test_no_credentials(db, make_user):
    with pytest.raises(NoCredentials):
        await get_scope(await make_user())
