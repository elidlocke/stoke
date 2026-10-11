"""Reading normalized payments and subscriptions from the stored Stripe objects."""

from dataclasses import replace

import pytest
from sqlalchemy import delete

from app import fetch, sync
from app.db_models import StripeObject
from app.stripe_client import Account, MissingPermission
from tests.conftest import make_failed_pi, make_invoice, make_pi
from tests.test_sync import ACCOUNT, account, page, run_imports, stripe_api  # noqa: F401 (fixtures)

API = "https://api.stripe.com/v1"


@pytest.fixture
async def ready(db, account, stripe_api):  # noqa: F811
    stripe_api.get(f"{API}/payment_intents").mock(return_value=page([
        make_pi(id="pi_new", created=2_000_000_000),
        make_failed_pi(id="pi_old", created=1_000_000_000),
        make_pi(id="pi_never", status="requires_payment_method", latest_charge=None, created=1_500_000_000),
    ], "payment_intents"))
    stripe_api.get(f"{API}/invoices").mock(return_value=page([
        make_invoice("pi_old", id="in_old", created=1_000_000_000 - 10 * 86400, billing_reason="manual", attempt_count=4),
    ], "invoices"))
    await sync.start_backfill(account.id, account.livemode)
    await run_imports()
    return account


async def test_payments_joined_to_invoices_and_customers(ready):
    payments = await fetch.payments_since(ready, None)
    assert [(p.id, p.status, p.attempts, p.billing_reason, p.email) for p in payments] == [
        ("pi_new", "succeeded", 1, None, "ada@example.com"),  # no invoice: a one-off payment
        ("pi_old", "failed", 4, "manual", "ada@example.com"),  # never-attempted pi skipped
    ]


async def test_window_reads_invoices_from_further_back(ready):
    # pi_old's invoice was created 10 days before the payment: outside the window, but still joined.
    payments = await fetch.payments_since(ready, 1_000_000_000)
    assert [(p.id, p.billing_reason) for p in payments] == [("pi_new", None), ("pi_old", "manual")]
    # A narrower window is filtered from the cached one.
    assert [p.id for p in await fetch.payments_since(ready, 1_000_000_001)] == ["pi_new"]


async def test_reads_are_cached_until_the_account_changes(ready, db):
    assert len(await fetch.payments_since(ready, None)) == 2
    async with db() as session:
        await session.execute(delete(StripeObject).where(StripeObject.id == "pi_new"))
        await session.commit()
    assert len(await fetch.payments_since(ready, None)) == 2
    fetch.clear_account(ready.id)
    assert len(await fetch.payments_since(ready, None)) == 1


async def test_subscriptions_with_their_customer(ready):
    subs = await fetch.subscriptions(ready)
    assert [(s.id, s.status, s.email) for s in subs] == [("sub_1", "active", "ada@example.com")]


async def test_each_user_sees_only_what_their_key_can_read(ready):
    # Stored objects are shared; a key without these permissions doesn't see them.
    with pytest.raises(MissingPermission, match="Subscriptions: Read"):
        await fetch.subscriptions(replace(ready, missing_permissions=("Subscriptions",), credential_id="other"))
    with pytest.raises(MissingPermission, match="PaymentIntents: Read"):
        await fetch.payments_since(replace(ready, missing_permissions=("PaymentIntents",), credential_id="other"), None)

    limited = replace(ready, missing_permissions=("Customers", "Invoices"), credential_id="limited")
    payments = await fetch.payments_since(limited, None)
    # No invoice join and no customer email: only what's on the payment itself.
    assert [(p.id, p.billing_reason, p.email) for p in payments] == [("pi_new", None, None), ("pi_old", None, None)]


async def test_accounts_are_kept_apart(ready):
    other = Account("acct_other", "Other", "usd", "connected", ACCOUNT.client)
    with pytest.raises(sync.Importing):  # nothing of acct_conn's is read as acct_other's
        await fetch.payments_since(other, None)
