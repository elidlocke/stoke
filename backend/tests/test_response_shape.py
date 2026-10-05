"""Regression guard: sensitive Stripe data must never appear in API responses."""

import time

import pytest
import stripe
from fastapi.testclient import TestClient

from app import fetch, fx, service
from app.aggregate import normalize_payment, normalize_subscription
from app.customer_id import customer_id
from app.main import app
from app.stripe_client import Account, AccountScope
from tests.conftest import (
    make_canceled_subscription,
    make_charge,
    make_failed_pi,
    make_invoice,
    make_pi,
    make_subscription,
)

FORBIDDEN = [
    "4242", "last4", "fingerprint", "visa", "exp_year",
    "address", "SENSITIVE", "phone", "+1555",
    "metadata", "receipt_url", "pay.stripe.com", "invoice.stripe.com", "secret",
    "pi_", "pm_", "cus_", "txn_", "in_1", "ch_", "\"fee\"",  # the JSON key; "feedback" is allowed
    "Ada Lovelace", "rk_test",
    "sub_", "si_", "price_", "comment",
]

PLATFORM = Account("acct_platform", "Platform", "usd", "platform", client=None)
CONNECTED = Account("acct_conn", "Creator", "gbp", "connected", client=None)


@pytest.fixture
def client(monkeypatch):
    async def scope(refresh=False):
        return AccountScope(accounts=[PLATFORM, CONNECTED], reporting_currency="usd")

    def payments(account):
        charge = make_charge(balance_transaction={"amount": 5000, "currency": account.settlement_currency})
        paid = make_pi(id=f"pi_ok_{account.id}", latest_charge=charge)
        failed = make_failed_pi(id=f"pi_fail_{account.id}")
        return [
            normalize_payment(paid, make_invoice(paid["id"]), account.id),
            normalize_payment(failed, make_invoice(failed["id"], billing_reason="manual", attempt_count=3), account.id),
        ]

    async def payments_since(account, since, refresh=False):
        return payments(account)

    async def get_rates(pairs, target):
        return {p: 1.25 for p in pairs}

    async def subscriptions(account, refresh=False):
        now = int(time.time())
        return [
            normalize_subscription(make_canceled_subscription(
                id=f"sub_gone_{account.id}", start_date=now - 3 * 86400, canceled_at=now - 86400, ended_at=now - 86400,
            ), account.id),
            normalize_subscription(make_subscription(id=f"sub_new_{account.id}", start_date=now - 3600), account.id),
        ]

    monkeypatch.setattr(service, "get_scope", scope)
    monkeypatch.setattr(fetch, "payments_since", payments_since)
    monkeypatch.setattr(fetch, "subscriptions", subscriptions)
    monkeypatch.setattr(fx, "get_rates", get_rates)
    return TestClient(app, raise_server_exceptions=False)


def assert_clean(text: str):
    leaked = [f for f in FORBIDDEN if f in text]
    assert not leaked, f"sensitive data leaked: {leaked}"


def test_leaderboard_shape(client):
    resp = client.get("/api/leaderboard", params={"period": "all"})
    assert resp.status_code == 200
    assert_clean(resp.text)
    body = resp.json()
    assert body["reporting_currency"] == "usd"
    [entry] = body["customers"]
    # $50 on the platform + £40 (5000 minor * 1.25 -> 6250) on the connected account; failures ignored.
    assert entry == {
        "rank": 1, "email": "ada@example.com", "customer_id": customer_id("ada@example.com"),
        "net_total": 11250, "payment_count": 2,
        "last_seen": 1_750_000_000, "accounts": ["acct_conn", "acct_platform"],
    }


def test_profile_shape(client):
    resp = client.get(f"/api/customers/{customer_id('ada@example.com')}")
    assert resp.status_code == 200
    assert_clean(resp.text)
    body = resp.json()
    assert body["summary"] == {
        "net": 11250, "gross": 11250, "refunded": 0, "payments": 2, "failed_payments": 2,
        "first_paid": 1_750_000_000, "last_paid": 1_750_000_000,
        "current_plan": "1 × Monthly (at $8.00 / month)",
    }
    kinds = sorted(e["kind"] for e in body["timeline"])
    assert kinds == ["payment_failed", "payment_failed", "subscribed", "subscribed"]
    failed = [e for e in body["timeline"] if e["kind"] == "payment_failed"]
    assert all(e["amount_reporting"] is None and e["attempts"] == 3 for e in failed)
    assert failed[0]["failure_message"] == "Your card was declined."


def test_accounts_shape(client):
    resp = client.get("/api/accounts")
    assert resp.status_code == 200
    assert_clean(resp.text)


def test_cancellations_shape(client):
    resp = client.get("/api/cancellations", params={"window": "7d"})
    assert resp.status_code == 200
    assert_clean(resp.text)  # notably, the customer's free-text cancellation comment
    body = resp.json()
    assert sorted(c["account_id"] for c in body["customers"]) == ["acct_conn", "acct_platform"]
    entry = body["customers"][0]
    assert (entry["reason"], entry["feedback"], entry["ended"]) == ("cancellation_requested", "too_expensive", True)
    assert entry["lifetime_value"] == 11250  # across both accounts
    assert entry["resubscribed"] is True  # the same email has a new subscription


def test_new_subscribers_shape(client):
    resp = client.get("/api/new-subscribers")
    assert resp.status_code == 200
    assert_clean(resp.text)
    entry = resp.json()["customers"][0]
    assert (entry["email"], entry["status"], entry["returning"]) == ("ada@example.com", "active", True)
    assert entry["plan"] == "1 × Monthly (at $8.00 / month)"


def test_anniversaries_shape(client):
    resp = client.get("/api/anniversaries", params={"window": "3m"})
    assert resp.status_code == 200
    assert_clean(resp.text)
    assert resp.json()["customers"] == []  # the fixture's payments are from mid-2025


def test_invalid_window_rejected(client):
    assert client.get("/api/cancellations", params={"window": "all"}).status_code == 422


def test_every_list_links_by_opaque_id(client):
    for path in ["/api/leaderboard", "/api/cancellations", "/api/anniversaries", "/api/new-subscribers"]:
        for c in client.get(path, params={"window": "3m"} if "leader" not in path else {}).json()["customers"]:
            assert c["customer_id"] == customer_id(c["email"])


def test_profile_of_subscriber_without_payments(client, monkeypatch):
    async def no_payments(account, since, refresh=False):
        return []

    monkeypatch.setattr(fetch, "payments_since", no_payments)
    resp = client.get(f"/api/customers/{customer_id('ada@example.com')}")
    assert resp.status_code == 200
    assert resp.json()["email"] == "ada@example.com"


def test_profile_rejects_emails_and_unknown_ids(client):
    assert client.get("/api/customers/ada@example.com").status_code == 422  # emails are no longer accepted
    assert client.get("/api/customers/cus_1").status_code == 422
    assert client.get("/api/customers/x' OR email:'y").status_code == 422
    assert client.get(f"/api/customers/{'0' * 24}").status_code == 404


def test_unknown_account_404(client):
    for path in ["/api/leaderboard", "/api/cancellations", "/api/anniversaries", "/api/new-subscribers"]:
        assert client.get(path, params={"account": "acct_nope"}).status_code == 404


def test_stripe_error_is_generic(client, monkeypatch):
    async def boom(account, since, refresh=False):
        raise stripe.AuthenticationError("Invalid API Key provided: rk_test_****SECRET")

    monkeypatch.setattr(fetch, "payments_since", boom)
    resp = client.get("/api/leaderboard")
    assert resp.status_code == 502
    assert resp.json() == {"detail": "Error talking to Stripe"}
    assert_clean(resp.text)
