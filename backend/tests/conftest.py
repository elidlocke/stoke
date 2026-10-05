import copy
import os

import dotenv

# Keep the developer's real .env (and its keys) out of tests.
dotenv.load_dotenv = lambda *args, **kwargs: False
os.environ.setdefault("STRIPE_API_KEY", "rk_test_dummy")

import pytest  # noqa: E402

from app import fetch  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.stripe_client import clear_scope_cache  # noqa: E402

SENSITIVE_CUSTOMER = {
    "id": "cus_1",
    "object": "customer",
    "email": "Ada@Example.com",
    "phone": "+15555550100",
    "address": {"line1": "1 SENSITIVE St"},
    "metadata": {"crm_id": "SENSITIVE_METADATA"},
}


def make_charge(**overrides) -> dict:
    """A successful charge with balance_transaction and refunds expanded.

    Deliberately includes sensitive fields so tests can assert they never reach API responses.
    """
    charge = {
        "id": "ch_1",
        "object": "charge",
        "amount": 5000,
        "amount_captured": 5000,
        "amount_refunded": 0,
        "currency": "usd",
        "created": 1_750_000_000,
        "status": "succeeded",
        "paid": True,
        "description": "Pro plan",
        "receipt_email": None,
        "receipt_url": "https://pay.stripe.com/receipts/secret-receipt",
        "payment_method": "pm_SENSITIVE",
        "metadata": {"internal_note": "SENSITIVE_METADATA"},
        "billing_details": {
            "email": None,
            "name": "Ada Lovelace",
            "phone": "+15555550100",
            "address": {"line1": "1 SENSITIVE St", "city": "London", "postal_code": "N1"},
        },
        "payment_method_details": {
            "type": "card",
            "card": {"brand": "visa", "last4": "4242", "fingerprint": "FPSENSITIVE", "exp_year": 2030},
        },
        "balance_transaction": {
            "id": "txn_1",
            "object": "balance_transaction",
            "amount": 5000,
            "currency": "usd",
            "exchange_rate": None,
            "fee": 175,
            "net": 4825,
        },
        "refunds": {"object": "list", "data": []},
    }
    charge.update(overrides)
    return charge


def make_pi(**overrides) -> dict:
    """A succeeded PaymentIntent shaped like Stripe's API with customer + latest_charge expanded."""
    pi = {
        "id": "pi_1",
        "object": "payment_intent",
        "amount": 5000,
        "currency": "usd",
        "created": 1_750_000_000,
        "status": "succeeded",
        "description": "Pro plan",
        "receipt_email": None,
        "client_secret": "pi_1_secret_SENSITIVE",
        "payment_method": "pm_SENSITIVE",
        "metadata": {"internal_note": "SENSITIVE_METADATA"},
        "customer": copy.deepcopy(SENSITIVE_CUSTOMER),
        "latest_charge": make_charge(),
        "last_payment_error": None,
    }
    pi.update(overrides)
    return pi


def make_failed_pi(**overrides) -> dict:
    return make_pi(**{
        "status": "requires_payment_method",
        "latest_charge": make_charge(
            status="failed", paid=False, amount_captured=0, balance_transaction=None,
            failure_code="card_declined",
        ),
        "last_payment_error": {
            "code": "card_declined",
            "message": "Your card was declined.",
            "payment_method": {"id": "pm_SENSITIVE", "card": {"last4": "4242"}},
        },
    } | overrides)


def make_invoice(pi_id: str, **overrides) -> dict:
    invoice = {
        "id": "in_1",
        "object": "invoice",
        "billing_reason": "subscription_create",
        "attempt_count": 1,
        "customer_email": "ada@example.com",
        "customer_address": {"line1": "1 SENSITIVE St"},
        "hosted_invoice_url": "https://invoice.stripe.com/SENSITIVE",
        "lines": {"data": [{"description": "1 × Monthly (at $8.00 / month)"}]},
        "payments": {"data": [{"payment": {"type": "payment_intent", "payment_intent": pi_id}}]},
    }
    invoice.update(overrides)
    return invoice


def _clear():
    fetch.clear_cache()
    clear_scope_cache()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_caches():
    _clear()
    yield
    _clear()
