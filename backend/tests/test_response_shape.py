"""Regression guard: sensitive Stripe data must never appear in API responses."""

import time
import uuid

import pytest
import stripe
from fastapi.testclient import TestClient

from app import fetch, fx, service
from app.aggregate import normalize_payment, normalize_subscription
from app.auth import CurrentUser, current_user
from app.customer_id import customer_id
from app.main import app
from app.stripe_client import Account, AccountScope, MissingPermission
from tests.conftest import (
    make_canceled_subscription,
    make_charge,
    make_dispute,
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
    "dp_", "evidence", "network_reason_code",
]

PLATFORM = Account("acct_platform", "Platform", "usd", "platform", client=None)
CONNECTED = Account("acct_conn", "Creator", "gbp", "connected", client=None)


USER = CurrentUser(id=uuid.uuid4(), auth_subject="auth0|test", email="owner@example.com")


@pytest.fixture
def client(monkeypatch):
    async def scope(user, refresh=False):
        assert user == USER
        return AccountScope(accounts=[PLATFORM, CONNECTED], reporting_currency="usd")

    def payments(account):
        charge = make_charge(balance_transaction={"amount": 5000, "currency": account.settlement_currency, "fee_details": [
            {"type": "application_fee", "amount": 500, "description": "Substack application fee"},
            {"type": "stripe_fee", "amount": 200, "description": "Stripe processing fees"},
        ]})
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
    app.dependency_overrides[current_user] = lambda: USER
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def assert_clean(text: str):
    leaked = [f for f in FORBIDDEN if f in text]
    assert not leaked, f"sensitive data leaked: {leaked}"


def test_leaderboard_shape(client):
    resp = client.get("/api/leaderboard", params={"period": "all"})
    assert resp.status_code == 200
    assert_clean(resp.text)
    body = resp.json()
    assert body["reporting_currency"] == "usd"
    assert body["customer_count"] == 1
    [entry] = body["customers"]
    # $50 on the platform + £40 (5000 minor * 1.25 -> 6250) on the connected account; failures ignored.
    assert entry == {
        "rank": 1, "email": "ada@example.com", "customer_id": customer_id("ada@example.com"),
        # $50 + £40 (* 1.25 = $50) on the two accounts, minus $7 and £7 (* 1.25 = $8.75) in fees.
        "take_home": 11250 - 700 - 875, "payment_count": 2,
        "last_seen": 1_750_000_000, "accounts": ["acct_conn", "acct_platform"],
    }


def test_profile_shape(client):
    resp = client.get(f"/api/customers/{customer_id('ada@example.com')}")
    assert resp.status_code == 200
    assert_clean(resp.text)
    body = resp.json()
    assert body["summary"] == {
        "take_home": 9675, "gross": 11250, "refunded": 0, "fees": 1575, "disputed": 0, "open_disputes": 0,
        "payments": 2, "failed_payments": 2,
        "first_paid": 1_750_000_000, "last_paid": 1_750_000_000,
        "current_plan": "Monthly",
    }
    kinds = sorted(e["kind"] for e in body["timeline"])
    assert kinds == ["payment_failed", "payment_failed", "subscribed", "subscribed"]
    failed = [e for e in body["timeline"] if e["kind"] == "payment_failed"]
    assert all(e["amount_reporting"] is None and e["attempts"] == 3 for e in failed)
    assert failed[0]["failure_message"] == "Your card was declined."
    paid = sorted((e for e in body["timeline"] if e["kind"] == "subscribed"), key=lambda e: e["amount_reporting"])
    assert paid[0]["fees"] == [
        {"type": "application_fee", "description": "Substack application fee", "amount": 500},
        {"type": "stripe_fee", "description": "Stripe processing fees", "amount": 200},
    ]
    assert paid[0]["take_home"] == 5000 - 700


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
    assert entry["lifetime_value"] == 9675  # take-home across both accounts
    assert entry["resubscribed"] is True  # the same email has a new subscription
    assert (entry["current_plan"], entry["current_since"] > entry["canceled_at"]) == ("Monthly", True)


def test_new_customers_shape(client, monkeypatch):
    async def recent_one_off(account, since, refresh=False):
        pi = make_pi(id=f"pi_{account.id}", created=int(time.time()) - 4 * 86400, description="Coaching session")
        return [normalize_payment(pi, None, account.id)]

    monkeypatch.setattr(fetch, "payments_since", recent_one_off)
    resp = client.get("/api/new-customers")
    assert resp.status_code == 200
    assert_clean(resp.text)
    [entry] = resp.json()["customers"]
    # Paid for coaching four days ago, before the fixture's subscriptions (three days and an hour ago).
    assert (entry["email"], entry["started_with"], entry["description"], entry["subscription_status"]) == (
        "ada@example.com", "purchase", "Coaching session", "active",
    )
    assert entry["customer_id"] == customer_id("ada@example.com")


def test_anniversaries_shape(client):
    resp = client.get("/api/anniversaries", params={"window": "3m"})
    assert resp.status_code == 200
    assert_clean(resp.text)
    assert resp.json()["customers"] == []  # the fixture's payments are from mid-2025


def test_invalid_window_rejected(client):
    assert client.get("/api/cancellations", params={"window": "all"}).status_code == 422


def test_every_list_links_by_opaque_id(client):
    for path in ["/api/leaderboard", "/api/cancellations", "/api/anniversaries", "/api/new-customers"]:
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


def test_customer_count_is_not_capped_by_limit(client, monkeypatch):
    def paid(i, account):
        pi = make_pi(id=f"pi_{i}", customer={"email": f"c{i}@x.com"})
        return normalize_payment(pi, None, account.id)

    async def many(account, since, refresh=False):
        return [paid(i, account) for i in range(5)]

    monkeypatch.setattr(fetch, "payments_since", many)
    body = client.get("/api/leaderboard", params={"period": "all", "limit": 2}).json()
    assert (len(body["customers"]), body["customer_count"]) == (2, 5)


def test_dispute_shape(client, monkeypatch):
    async def disputed_payment(account, since, refresh=False):
        pi = make_pi(id=f"pi_{account.id}", latest_charge=make_charge(dispute=make_dispute("needs_response")))
        return [normalize_payment(pi, make_invoice(pi["id"]), account.id)]

    monkeypatch.setattr(fetch, "payments_since", disputed_payment)
    resp = client.get(f"/api/customers/{customer_id('ada@example.com')}")
    assert resp.status_code == 200
    assert_clean(resp.text)  # notably, the dispute's evidence (customer name, address, email) isn't returned
    body = resp.json()
    assert body["summary"]["open_disputes"] == 2
    [first, *_] = [e for e in body["timeline"] if e["kind"] == "disputed"]
    assert (first["dispute_status"], first["dispute_reason"], first["fees"][0]["description"]) == (
        "needs_response", "fraudulent", "Dispute fee",
    )


def test_at_risk_shape(client, monkeypatch):
    now = int(time.time())

    async def payments_since(account, since, refresh=False):
        failed = make_failed_pi(id=f"pi_fail_{account.id}")
        disputed = make_pi(id=f"pi_dp_{account.id}", latest_charge=make_charge(
            dispute=make_dispute("needs_response", evidence_details={"due_by": now + 5 * 86400}),
        ))
        return [normalize_payment(failed, None, account.id), normalize_payment(disputed, None, account.id)]

    async def subscriptions(account, refresh=False):
        failing_invoice = make_invoice("x", amount_due=800, currency="usd", attempt_count=2,
                                       created=now - 86400, next_payment_attempt=now + 2 * 86400)
        return [
            normalize_subscription(make_subscription(
                id=f"sub_due_{account.id}", status="past_due", latest_invoice=failing_invoice,
            ), account.id),
            normalize_subscription(make_subscription(
                id=f"sub_end_{account.id}", customer={"email": "bo@x.com"}, canceled_at=now - 86400,
                cancel_at=now + 9 * 86400, cancel_at_period_end=True,
                cancellation_details={"reason": "cancellation_requested", "feedback": "unused", "comment": "SENSITIVE"},
            ), account.id),
        ]

    monkeypatch.setattr(fetch, "payments_since", payments_since)
    monkeypatch.setattr(fetch, "subscriptions", subscriptions)
    resp = client.get("/api/at-risk", params={"account": "acct_conn"})
    assert resp.status_code == 200
    assert_clean(resp.text)  # notably, the cancellation comment and the dispute's evidence
    body = resp.json()
    assert [(c["kind"], c["email"]) for c in body["customers"]] == [
        ("payment_failing", "ada@example.com"),  # retried in 2 days
        ("dispute", "ada@example.com"),  # respond within 5
        ("canceling", "bo@x.com"),  # access ends in 9
    ]
    failing, _, canceling = body["customers"]
    assert (failing["amount"], failing["attempts"], failing["failure_message"]) == (800, 2, "Your card was declined.")
    assert canceling["feedback"] == "unused"
    for c in body["customers"]:
        assert c["customer_id"] == customer_id(c["email"])


def test_trends_shape(client):
    resp = client.get("/api/trends")
    assert resp.status_code == 200
    assert_clean(resp.text)
    body = resp.json()
    assert (len(body["months"]), body["churn_available"]) == (12, True)
    assert [m["partial"] for m in body["months"]] == [False] * 11 + [True]
    assert sum(m["take_home"] for m in body["months"]) == 0  # the fixture's payments are from 2025


def test_trends_without_subscriptions_access(client, monkeypatch):
    async def forbidden(account, refresh=False):
        raise MissingPermission("Subscriptions")

    monkeypatch.setattr(fetch, "subscriptions", forbidden)
    body = client.get("/api/trends").json()
    assert body["churn_available"] is False


def test_unknown_account_404(client):
    for path in ["/api/leaderboard", "/api/cancellations", "/api/anniversaries", "/api/new-customers", "/api/at-risk"]:
        assert client.get(path, params={"account": "acct_nope"}).status_code == 404


def test_stripe_error_is_generic(client, monkeypatch):
    async def boom(account, since, refresh=False):
        raise stripe.AuthenticationError("Invalid API Key provided: rk_test_****SECRET")

    monkeypatch.setattr(fetch, "payments_since", boom)
    resp = client.get("/api/leaderboard")
    assert resp.status_code == 502
    assert resp.json() == {"detail": "Error talking to Stripe"}
    assert_clean(resp.text)
