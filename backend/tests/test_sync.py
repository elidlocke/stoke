"""Importing accounts into Postgres and keeping them current: the first import, refresh, webhooks."""

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest
import respx
import stripe
from sqlalchemy import func, select, update

from app import credentials, fetch, sync
from app.auth import current_user
from app.config import get_settings
from app.db_models import StripeAccount, StripeBackfill, StripeCredential, StripeObject, StripeSyncQueue
from app.main import app
from app.stripe_client import STRIPE_API_VERSION, Account
from tests.conftest import (
    add_key,
    SENSITIVE_CUSTOMER,
    make_charge,
    make_invoice,
    make_pi,
    make_subscription,
    mock_stripe_keys,
    stripe_account,
)

API = "https://api.stripe.com/v1"


def no_retry_client(key="sk_test_platform") -> stripe.StripeClient:
    return stripe.StripeClient(key, stripe_version=STRIPE_API_VERSION, max_network_retries=0,
                               http_client=stripe.HTTPXClient())


ACCOUNT = Account("acct_conn", "Creator", "usd", no_retry_client())


def page(data, path, has_more=False):
    return httpx.Response(200, json={"object": "list", "url": f"/v1/{path}", "has_more": has_more, "data": data})


def query(call) -> dict:
    return parse_qs(call.request.url.query.decode())


def event(obj: dict, created: int | None = None, **extra) -> dict:
    return {"id": "evt_1", "object": "event", "type": "x.updated", "created": created or int(time.time()),
            "livemode": False, "data": {"object": obj}, **extra}


@pytest.fixture
def account(monkeypatch):
    """The worker reaches ACCOUNT without a stored key."""
    async def account_for(account_id, livemode, need=None):
        return ACCOUNT if account_id == ACCOUNT.id else None
    monkeypatch.setattr(sync, "account_for", account_for)
    return ACCOUNT


@pytest.fixture
def stripe_api():
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{API}/payment_intents").mock(return_value=page([make_pi()], "payment_intents"))
        mock.get(f"{API}/invoices").mock(return_value=page([make_invoice("pi_1")], "invoices"))
        mock.get(f"{API}/subscriptions").mock(return_value=page([make_subscription()], "subscriptions"))
        mock.get(f"{API}/customers").mock(return_value=page([SENSITIVE_CUSTOMER], "customers"))
        mock.get(f"{API}/events").mock(return_value=page([], "events"))
        yield mock


async def run_imports() -> None:
    while (b := await sync._claim_backfill()) is not None:
        await sync.run_backfill(b)


async def backfills(db) -> dict[str, StripeBackfill]:
    async with db() as session:
        return {b.object: b for b in await session.scalars(select(StripeBackfill))}


async def stored(db) -> list[StripeObject]:
    async with db() as session:
        return list(await session.scalars(select(StripeObject).order_by(StripeObject.object, StripeObject.id)))


async def imported(db, account) -> StripeAccount:
    await sync.start_backfill(account.id, account.livemode)
    await run_imports()
    async with db() as session:
        return await session.get(StripeAccount, (account.id, account.livemode))


def test_api_version_is_the_sdks():
    # Upgrading stripe-python changes its pinned version: update STRIPE_API_VERSION deliberately,
    # then run scripts/resync.py.
    assert STRIPE_API_VERSION == stripe.api_version


# --- First import ---------------------------------------------------------------------------------


async def test_first_read_starts_the_import_and_waits_for_it(db, account, stripe_api):
    with pytest.raises(sync.Importing):
        await fetch.payments_since(account, None)
    assert {o: b.state for o, b in (await backfills(db)).items()} == dict.fromkeys(sync.OBJECT_TYPES, "pending")
    assert not stripe_api.calls  # the import runs in the background, not in the request

    await run_imports()

    payments = await fetch.payments_since(account, None)
    assert [(p.id, p.email, p.billing_reason) for p in payments] == [("pi_1", "ada@example.com", "subscription_create")]
    assert [s.id for s in await fetch.subscriptions(account)] == ["sub_1"]


async def test_import_stores_only_the_projection_read_at_the_pinned_version(db, account, stripe_api):
    await imported(db, account)

    rows = await stored(db)
    assert [(r.object, r.id) for r in rows] == [
        ("customer", "cus_1"), ("invoice", "in_1"), ("payment_intent", "pi_1"), ("subscription", "sub_1"),
    ]
    text = json.dumps([r.data for r in rows])
    assert "SENSITIVE" not in text and "Ada Lovelace" not in text and "@example.com" not in text.lower()
    assert all(r.version == sync.SYNC_VERSION for r in rows)

    for path, expand in [("payment_intents", sync.EXPAND["payment_intent"]), ("subscriptions", ["latest_invoice"])]:
        call = next(c for c in stripe_api.calls if c.request.url.path == f"/v1/{path}")
        assert call.request.headers["Stripe-Version"] == STRIPE_API_VERSION
        q = query(call)
        assert [v for k, v in sorted(q.items()) if k.startswith("expand")] == [[f"data.{e}"] for e in expand]
    sub_call = next(c for c in stripe_api.calls if c.request.url.path == "/v1/subscriptions")
    assert query(sub_call)["status"] == ["all"]


async def test_import_cursor_is_set_before_anything_is_listed(db, account, stripe_api):
    before = datetime.now(UTC)
    await sync.start_backfill(account.id, account.livemode)
    row = await sync.account_row(account.id, account.livemode)
    assert row.events_cursor >= before and row.backfilled_at is None

    await run_imports()
    events = next(c for c in stripe_api.calls if c.request.url.path == "/v1/events")
    # Changes made while the import ran are replayed from the cursor once it finishes.
    assert query(events)["created[gt]"] == [str(int((row.events_cursor - sync.CURSOR_OVERLAP).timestamp()))]


async def test_interrupted_import_resumes_where_it_stopped(db, account, stripe_api):
    stripe_api.get(f"{API}/payment_intents").mock(side_effect=[
        page([make_pi(id="pi_2", created=2)], "payment_intents", has_more=True),
        httpx.Response(500, json={"error": {"type": "api_error", "message": "boom"}}),
        page([make_pi(id="pi_1", created=1)], "payment_intents"),
    ])
    await sync.start_backfill(account.id, account.livemode)
    await run_imports()

    pi = (await backfills(db))["payment_intent"]
    assert (pi.state, pi.starting_after, pi.count, pi.attempts) == ("pending", "pi_2", 1, 1)
    assert pi.retry_at is not None
    with pytest.raises(sync.Importing):
        await fetch.payments_since(account, None)

    async with db() as session:
        await session.execute(update(StripeBackfill).values(retry_at=None))
        await session.commit()
    await run_imports()

    resumed = [c for c in stripe_api.calls if c.request.url.path == "/v1/payment_intents"][-1]
    assert query(resumed)["starting_after"] == ["pi_2"]
    assert (await backfills(db))["payment_intent"].count == 2
    assert [p.id for p in await fetch.payments_since(account, None)] == ["pi_2", "pi_1"]


async def test_a_stale_import_is_taken_over(db, account, stripe_api):
    await sync.start_backfill(account.id, account.livemode, ["Customers", "Invoices", "Subscriptions"])
    first = await sync._claim_backfill()
    async with db() as session:  # its process died: no heartbeat since
        await session.execute(update(StripeBackfill).where(StripeBackfill.object == first.object).values(
            heartbeat_at=datetime.now(UTC) - timedelta(minutes=5)
        ))
        await session.commit()

    second = await sync._claim_backfill()
    assert second.object == first.object and second.started_at != first.started_at

    await sync.run_backfill(first)  # the old run, if it was only slow, stops without writing
    assert (await backfills(db))[first.object].count == 0
    await sync.run_backfill(second)
    assert (await backfills(db))[first.object].state == "done"


async def test_types_the_key_cant_read_are_skipped(db, account, stripe_api):
    stripe_api.get(f"{API}/subscriptions").mock(return_value=httpx.Response(403, json={
        "error": {"type": "invalid_request_error", "message": "restricted key"}
    }))
    row = await imported(db, account)

    assert (await backfills(db))["subscription"].state == "skipped"
    assert row.backfilled_at is not None  # the rest is ready


async def test_permissions_known_up_front_skip_without_asking_stripe(db, account, stripe_api):
    await sync.start_backfill(account.id, account.livemode, ["Subscriptions"])
    assert (await backfills(db))["subscription"].state == "skipped"
    await run_imports()
    assert not [c for c in stripe_api.calls if c.request.url.path == "/v1/subscriptions"]


async def test_a_key_that_can_read_nothing_is_ready_at_once(db, account):
    await sync.start_backfill(account.id, account.livemode, sync.PERMISSION.values())
    assert (await sync.account_row(account.id, account.livemode)).backfilled_at is not None


# --- With stored keys -----------------------------------------------------------------------------

KEY_A = "rk_test_" + "a" * 24 + "A1b2"
KEY_A2 = "rk_test_" + "z" * 24 + "Z9y8"


@pytest.fixture
def keys():
    with respx.mock(assert_all_called=False) as mock:
        mock_stripe_keys(mock, {KEY_A: stripe_account("acct_a", "Creator A"), KEY_A2: stripe_account("acct_a", "Creator A")})
        yield mock


async def test_adding_a_key_starts_the_import(db, make_user, keys):
    async with db() as session:
        await add_key(session, await make_user(), KEY_A)
    assert {b.state for b in (await backfills(db)).values()} == {"pending"}

    await run_imports()
    assert (await sync.account_row("acct_a", False)).backfilled_at is not None


async def test_second_key_to_an_imported_account_imports_nothing(db, make_user, keys):
    async with db() as session:
        await add_key(session, await make_user(), KEY_A)
    await run_imports()
    calls = len(keys.calls)

    async with db() as session:
        await add_key(session, await make_user(), KEY_A2)
    assert {b.state for b in (await backfills(db)).values()} == {"done"}
    assert await sync._claim_backfill() is None
    assert len(keys.calls) - calls == 1 + len(credentials.PERMISSION_CHECKS)  # only the key's own check


async def test_a_key_revoked_mid_import_is_marked_invalid(db, make_user, keys):
    async with db() as session:
        cred = await add_key(session, await make_user(), KEY_A)
    keys.routes.clear()
    mock_stripe_keys(keys, {})  # Stripe now rejects the key
    await run_imports()

    async with db() as session:
        assert (await session.get(StripeCredential, cred.id)).status == "invalid"
    assert {b.state for b in (await backfills(db)).values()} == {"failed"}


async def test_removing_the_last_key_deletes_the_stored_data(db, make_user, keys):
    first, second = await make_user(), await make_user()
    async with db() as session:
        cred_1 = await add_key(session, first, KEY_A)
        cred_2 = await add_key(session, second, KEY_A2)
    keys.get(f"{API}/customers").mock(return_value=page([SENSITIVE_CUSTOMER], "customers"))
    await run_imports()
    assert await stored(db)

    async with db() as session:
        await credentials.delete(session, first, cred_1.id)
    assert await stored(db)  # the other user's key still reads it
    async with db() as session:
        await credentials.delete(session, second, cred_2.id)
    assert not await stored(db)
    assert await sync.account_row("acct_a", False) is None


async def test_failed_import_is_retried_from_settings(db, make_user, keys):
    user = await make_user()
    async with db() as session:
        cred = await add_key(session, user, KEY_A)
        await session.execute(update(StripeBackfill).values(state="failed", error="x"))
        await session.commit()
        await credentials.retry_sync(session, user, cred.id)
    assert {b.state for b in (await backfills(db)).values()} == {"pending"}


async def test_reimport_starts_every_import_again(db, make_user, keys):
    user = await make_user()
    async with db() as session:
        cred = await add_key(session, user, KEY_A)
        await session.execute(update(StripeBackfill).values(state="done", count=7, starting_after="cus_7"))
        await session.commit()
        await credentials.reimport(session, user, cred.id)
    found = await backfills(db)
    assert {(b.state, b.count, b.starting_after) for b in found.values()} == {("pending", 0, None)}


# --- Keeping it current ---------------------------------------------------------------------------


async def test_refresh_replays_events_and_rereads_what_they_name(db, account, stripe_api):
    await imported(db, account)
    assert (await fetch.payments_since(account, None))[0].amount_refunded == 0

    stripe_api.get(f"{API}/events").mock(return_value=page([
        event(make_charge(payment_intent="pi_1")),  # a refund on an old payment
        event({"id": "evt_x", "object": "unknown_thing"}),
    ], "events"))
    refunded = make_pi(latest_charge=make_charge(amount_refunded=1000))
    retrieve = stripe_api.get(f"{API}/payment_intents/pi_1").mock(return_value=httpx.Response(200, json=refunded))

    payments = await fetch.payments_since(account, None, refresh=True)

    assert payments[0].amount_refunded == 1000
    assert query(retrieve.calls[0])["expand[0]"] == ["latest_charge.balance_transaction"]
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(StripeSyncQueue)) == 0


async def test_refresh_after_more_than_29_days_imports_again(db, account, stripe_api):
    await imported(db, account)
    async with db() as session:
        await session.execute(update(StripeAccount).values(events_cursor=datetime.now(UTC) - timedelta(days=40)))
        await session.commit()
    events_calls = len([c for c in stripe_api.calls if c.request.url.path == "/v1/events"])

    payments = await fetch.payments_since(account, None, refresh=True)

    assert [p.id for p in payments] == ["pi_1"]  # what's stored is shown meanwhile
    assert {b.state for b in (await backfills(db)).values()} == {"pending"}
    assert len([c for c in stripe_api.calls if c.request.url.path == "/v1/events"]) == events_calls

    await fetch.payments_since(account, None, refresh=True)  # a second refresh doesn't restart it
    pending = await sync._claim_backfill()
    await sync.run_backfill(pending)
    assert (await backfills(db))[pending.object].state == "done"


async def test_an_older_read_never_overwrites_a_newer_one(db, account, stripe_api):
    row = await imported(db, account)
    key = await sync.account_key(row)
    async with db() as session, session.begin():
        await sync._upsert(session, row, key, sync.SYNC_VERSION, "payment_intent",
                           [make_pi(amount=1)], datetime(2000, 1, 1, tzinfo=UTC))
    assert next(r for r in await stored(db) if r.id == "pi_1").data["amount"] == 5000


async def test_a_notice_during_a_reread_keeps_the_object_queued(db, account, stripe_api):
    await imported(db, account)
    await sync.enqueue(account.id, False, [("payment_intent", "pi_1")])
    [job] = await sync._claim_jobs(None)
    await sync.enqueue(account.id, False, [("payment_intent", "pi_1")])  # it changed again meanwhile

    stripe_api.get(f"{API}/payment_intents/pi_1").mock(return_value=httpx.Response(200, json=make_pi()))
    await sync._process(job, None)

    async with db() as session:
        left = list(await session.scalars(select(StripeSyncQueue)))
    assert [(j.id, j.claimed_at) for j in left] == [("pi_1", None)]


async def test_an_object_deleted_in_stripe_is_deleted(db, account, stripe_api):
    stripe_api.get(f"{API}/invoices").mock(return_value=page([make_invoice("pi_1", id="in_draft")], "invoices"))
    await imported(db, account)
    stripe_api.get(f"{API}/invoices/in_draft").mock(return_value=httpx.Response(404, json={
        "error": {"type": "invalid_request_error", "code": "resource_missing", "message": "No such invoice"}
    }))
    await sync.enqueue(account.id, False, [("invoice", "in_draft")])
    await sync.drain()
    assert "in_draft" not in [r.id for r in await stored(db)]


@pytest.mark.parametrize("obj, expected", [
    ({"object": "payment_intent", "id": "pi_1"}, [("payment_intent", "pi_1")]),
    ({"object": "charge", "id": "ch_1", "payment_intent": "pi_1"}, [("payment_intent", "pi_1")]),
    ({"object": "refund", "id": "re_1", "payment_intent": {"id": "pi_1"}}, [("payment_intent", "pi_1")]),
    ({"object": "dispute", "id": "dp_1", "payment_intent": "pi_1"}, [("payment_intent", "pi_1")]),
    ({"object": "charge", "id": "ch_1", "payment_intent": None}, []),
    ({"object": "invoice", "id": "in_1", "subscription": "sub_1"}, [("invoice", "in_1"), ("subscription", "sub_1")]),
    ({"object": "invoice", "id": "in_1", "parent": {"subscription_details": {"subscription": "sub_1"}}},
     [("invoice", "in_1"), ("subscription", "sub_1")]),
    ({"object": "invoice_payment", "id": "inpay_1", "invoice": "in_1"}, [("invoice", "in_1")]),
    ({"object": "subscription", "id": "sub_1"}, [("subscription", "sub_1")]),
    ({"object": "customer", "id": "cus_1"}, [("customer", "cus_1")]),
    ({"object": "payout", "id": "po_1"}, []),
])
def test_targets(obj, expected):
    assert sync.targets(obj) == expected


# --- Webhooks -------------------------------------------------------------------------------------

SECRET = "whsec_test"


@pytest.fixture
async def api(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        yield client


def signed(payload: bytes, secret: str = SECRET) -> dict:
    t = int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"}


async def queued(db) -> list[tuple[str, str, str]]:
    async with db() as session:
        return [(j.account_id, j.object, j.id) for j in await session.scalars(select(StripeSyncQueue))]


async def test_webhook_queues_the_object_and_moves_the_cursor(db, account, stripe_api, api):
    await imported(db, account)
    created = int(time.time()) + 5
    body = json.dumps(event(make_charge(payment_intent="pi_1"), created, account="acct_conn")).encode()

    resp = await api.post("/api/stripe/webhook", content=body, headers=signed(body))

    assert resp.status_code == 200
    assert await queued(db) == [("acct_conn", "payment_intent", "pi_1")]
    assert (await sync.account_row("acct_conn", False)).events_cursor == datetime.fromtimestamp(created, UTC)


async def test_webhook_rejects_a_bad_signature(db, api):
    body = json.dumps(event({"object": "customer", "id": "cus_1"}, account="acct_conn")).encode()
    resp = await api.post("/api/stripe/webhook", content=body, headers=signed(body, "whsec_other"))
    assert resp.status_code == 400
    assert await queued(db) == []


async def test_webhook_ignores_accounts_stoke_doesnt_store(db, api):
    body = json.dumps(event({"object": "customer", "id": "cus_1"}, account="acct_unknown")).encode()
    assert (await api.post("/api/stripe/webhook", content=body, headers=signed(body))).status_code == 200
    assert await queued(db) == []


async def test_webhook_is_off_without_a_secret(db):
    get_settings.cache_clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        assert (await client.post("/api/stripe/webhook", content=b"{}")).status_code == 404


# --- What the dashboard sees ----------------------------------------------------------------------


async def test_views_report_the_import_and_its_progress(db, make_user, keys, api):
    user = await make_user()
    async with db() as session:
        await add_key(session, user, KEY_A)
    app.dependency_overrides[current_user] = lambda: user
    try:
        resp = await api.get("/api/leaderboard")
        assert resp.status_code == 503 and resp.json()["code"] == "importing"
        status = (await api.get("/api/sync-status")).json()
        assert status["accounts"][0]["state"] == "importing"
        assert [o["object"] for o in status["accounts"][0]["objects"]] == list(sync.OBJECT_TYPES)
        assert (await api.get("/api/credentials")).json()["credentials"][0]["sync_state"] == "importing"

        await run_imports()
        assert (await api.get("/api/leaderboard")).status_code == 200
        assert (await api.get("/api/sync-status")).json()["accounts"][0]["state"] == "ready"
    finally:
        app.dependency_overrides.clear()


async def test_refresh_without_events_access_imports_again(db, account, stripe_api):
    await imported(db, account)
    stripe_api.get(f"{API}/events").mock(return_value=httpx.Response(403, json={
        "error": {"type": "invalid_request_error", "message": "restricted key lacks rak_event_read"}
    }))
    assert [p.id for p in await fetch.payments_since(account, None, refresh=True)] == ["pi_1"]
    assert {b.state for b in (await backfills(db)).values()} == {"pending"}
