"""Regression guard: sensitive Stripe data must never appear in API responses."""

import pytest
import stripe
from fastapi.testclient import TestClient

from app import fetch, fx, service
from app.aggregate import normalize_payment
from app.main import app
from app.stripe_client import Account, AccountScope
from tests.conftest import make_charge, make_failed_pi, make_invoice, make_pi

FORBIDDEN = [
    "4242", "last4", "fingerprint", "visa", "exp_year",
    "address", "SENSITIVE", "phone", "+1555",
    "metadata", "receipt_url", "pay.stripe.com", "invoice.stripe.com", "secret",
    "pi_", "pm_", "cus_", "txn_", "in_1", "ch_", "fee",
    "Ada Lovelace", "rk_test",
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

    monkeypatch.setattr(service, "get_scope", scope)
    monkeypatch.setattr(fetch, "payments_since", payments_since)
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
        "rank": 1, "email": "ada@example.com", "net_total": 11250, "payment_count": 2,
        "last_seen": 1_750_000_000, "accounts": ["acct_conn", "acct_platform"],
    }


def test_profile_shape(client):
    resp = client.get("/api/customers/ADA@example.com")
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


def test_invalid_email_rejected(client):
    assert client.get("/api/customers/not-an-email").status_code == 422
    assert client.get("/api/customers/x' OR email:'y").status_code == 422


def test_unknown_account_404(client):
    assert client.get("/api/leaderboard", params={"account": "acct_nope"}).status_code == 404


def test_stripe_error_is_generic(client, monkeypatch):
    async def boom(account, since, refresh=False):
        raise stripe.AuthenticationError("Invalid API Key provided: rk_test_****SECRET")

    monkeypatch.setattr(fetch, "payments_since", boom)
    resp = client.get("/api/leaderboard")
    assert resp.status_code == 502
    assert resp.json() == {"detail": "Error talking to Stripe"}
    assert_clean(resp.text)
