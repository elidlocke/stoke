"""What's stored of each Stripe object: enough for every view, and no personal data but encrypted emails."""

import json
import os

import pytest

from app.aggregate import normalize_payment, normalize_subscription
from app.projection import SEALED_PREFIX, project, unseal
from tests.conftest import (
    SENSITIVE_CUSTOMER,
    make_canceled_subscription,
    make_charge,
    make_dispute,
    make_failed_pi,
    make_invoice,
    make_pi,
    make_subscription,
)

KEY = os.urandom(32)

PAYMENTS = {
    "succeeded": make_pi(),
    "failed": make_failed_pi(),
    "refunded": make_pi(latest_charge=make_charge(amount_refunded=2000, refunds={"object": "list", "data": [
        {"id": "re_1", "amount": 2000, "created": 1_751_000_000, "status": "succeeded", "metadata": {"x": "SENSITIVE"}},
    ]})),
    "disputed": make_pi(latest_charge=make_charge(dispute=make_dispute(returned=True))),
    "guest": make_pi(customer=None, receipt_email="Guest@Example.com", latest_charge=make_charge(
        billing_details={"email": "billing@example.com", "name": "Ada Lovelace", "address": {"line1": "1 SENSITIVE St"}},
    )),
}
SUBSCRIPTIONS = {
    "active": make_subscription(),
    "canceled": make_canceled_subscription(),
    "plan_change": make_subscription(
        items={"data": [{"price": {"id": "price_1", "nickname": "Annual"}}]},
        latest_invoice=make_invoice("pi_1", lines={"data": [
            {"description": "Unused time on Monthly", "amount": -500, "parent": {"subscription_item_details": {"proration": True}}},
            {"description": "Remaining time on Annual after 30 Sep 2026", "amount": 9000, "proration": True},
        ]}),
    ),
}


def stored(obj_type: str, obj: dict) -> dict:
    """Stored, then read back as app/fetch.py does: decrypted, with the stored customer put back."""
    data = unseal(project(obj_type, obj, KEY), KEY)
    if isinstance(obj.get("customer"), dict):
        data["customer"] = unseal(project("customer", obj["customer"], KEY), KEY)
    return data


@pytest.mark.parametrize("name", PAYMENTS)
def test_payments_read_the_same_from_storage(name):
    pi = PAYMENTS[name]
    invoice = make_invoice(pi["id"], billing_reason="subscription_cycle", attempt_count=2)
    assert normalize_payment(stored("payment_intent", pi), stored("invoice", invoice), "acct_1") == \
        normalize_payment(pi, invoice, "acct_1")


@pytest.mark.parametrize("name", SUBSCRIPTIONS)
def test_subscriptions_read_the_same_from_storage(name):
    sub = SUBSCRIPTIONS[name]
    assert normalize_subscription(stored("subscription", sub), "acct_1") == normalize_subscription(sub, "acct_1")


@pytest.mark.parametrize("obj_type, obj", [
    *(("payment_intent", pi) for pi in PAYMENTS.values()),
    *(("subscription", s) for s in SUBSCRIPTIONS.values()),
    ("invoice", make_invoice("pi_1")),
    ("customer", SENSITIVE_CUSTOMER),
])
def test_nothing_personal_is_stored_but_encrypted_emails(obj_type, obj):
    text = json.dumps(project(obj_type, obj, KEY))
    for leaked in ("SENSITIVE", "Ada Lovelace", "4242", "fingerprint", "pm_", "secret", "phone", "address",
                   "metadata", "\"evidence\"", "comment", "@example.com", "@Example.com"):
        assert leaked not in text


def test_emails_are_encrypted_under_the_account_key():
    data = project("customer", SENSITIVE_CUSTOMER, KEY)
    assert data["email"].startswith(SEALED_PREFIX)
    assert unseal(data, KEY)["email"] == "Ada@Example.com"
    assert unseal(data, os.urandom(32))["email"] is None  # another account's key reads nothing


def test_expanded_references_keep_only_their_id():
    assert project("payment_intent", make_pi(), KEY)["customer"] == "cus_1"
    assert project("payment_intent", make_pi(customer="cus_9"), KEY)["customer"] == "cus_9"
    assert project("payment_intent", make_pi(latest_charge="ch_1"), KEY)["latest_charge"] == "ch_1"


def test_prices_and_application_are_kept():
    price = {
        "id": "price_1", "object": "price", "nickname": "Founding", "unit_amount": 15000, "currency": "usd",
        "recurring": {"interval": "year", "interval_count": 1, "usage_type": "licensed"},
        "metadata": {"x": "SENSITIVE"}, "product": "prod_1",
    }
    stored = project("subscription", make_subscription(items={"data": [{"id": "si_1", "price": price}]}), KEY)
    assert stored["items"]["data"][0]["price"] == {
        "id": "price_1", "nickname": "Founding", "unit_amount": 15000, "currency": "usd",
        "recurring": {"interval": "year", "interval_count": 1},
    }
    pi = make_pi(application={"id": "ca_substack", "name": "Substack"}, latest_charge=make_charge(application="ca_substack"))
    stored = project("payment_intent", pi, KEY)
    assert (stored["application"], stored["latest_charge"]["application"]) == ("ca_substack", "ca_substack")
