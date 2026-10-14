"""What Stoke stores of each Stripe object: an allowlist of fields, kept in Stripe's own shape.

A stored object is the API object with every field not listed here removed, so the normalizers in
app/aggregate.py read it exactly as they read a live one. A field Stripe adds in a new API version
is dropped until it's listed. Addresses, phone numbers, card details (beyond brand, funding and
issuing country), cardholder names, metadata, free-text comments and dispute evidence are never listed.

The only personal data kept is each customer's email address (Stoke identifies customers by it) and
the name on their customer record (to greet them in notes). Both are stored encrypted ("enc:v1:…")
under the account's own data key (see app/sync.py), and decrypted on read.

Changing a projection changes what's stored: bump PROJECTION_REV, then run scripts/resync.py.
"""

import base64
from typing import Any

from app.crypto import DecryptionError, aead_open, aead_seal

PROJECTION_REV = 3  # 2: subscription prices and payments' Connect application; 3: names and analytics fields

KEEP = "keep"  # the value as is
SEAL = "seal"  # an email address: stored encrypted
ID = "id"  # an expandable reference: only its id, even if Stripe returned the expanded object

SEALED_PREFIX = "enc:v1:"
_AAD = b"stoke:stripe-email"

Spec = dict[str, Any]

# A discount as Stripe expands it: the coupon's terms, never who redeemed it. Kept for win-back
# discounts and for telling discounted subscribers apart.
_DISCOUNT: Spec = {
    "id": KEEP, "start": KEEP, "end": KEEP, "promotion_code": ID,
    "coupon": {
        "id": KEEP, "name": KEEP, "percent_off": KEEP, "amount_off": KEEP, "currency": KEEP,
        "duration": KEEP, "duration_in_months": KEEP,
    },
    # Newer API versions nest the coupon under source.
    "source": {"type": KEEP, "coupon": ID},
}

_PRICE: Spec = {
    "id": KEEP, "nickname": KEEP, "unit_amount": KEEP, "currency": KEEP, "type": KEEP, "product": ID,
    "lookup_key": KEEP, "recurring": {"interval": KEEP, "interval_count": KEEP, "usage_type": KEEP},
}

_INVOICE: Spec = {
    "id": KEEP, "object": KEEP, "created": KEEP, "status": KEEP, "currency": KEEP,
    "customer_email": SEAL,  # a snapshot that survives the customer's deletion
    "billing_reason": KEEP, "attempt_count": KEEP, "amount_due": KEEP, "next_payment_attempt": KEEP,
    "attempted": KEEP, "collection_method": KEEP,
    "amount_paid": KEEP, "amount_remaining": KEEP, "subtotal": KEEP, "total": KEEP,
    "period_start": KEEP, "period_end": KEEP,
    "status_transitions": {"finalized_at": KEEP, "paid_at": KEEP, "voided_at": KEEP, "marked_uncollectible_at": KEEP},
    "discount": _DISCOUNT,  # older API versions
    "discounts": ID,
    "total_discount_amounts": {"amount": KEEP, "discount": ID},
    "subscription": ID,  # older API versions
    "parent": {"subscription_details": {"subscription": ID}},
    "lines": {"data": {
        "description": KEEP, "amount": KEEP, "currency": KEEP, "quantity": KEEP, "proration": KEEP,
        "period": {"start": KEEP, "end": KEEP},
        "discount_amounts": {"amount": KEEP, "discount": ID},
        "pricing": {"price_details": {"price": ID, "product": ID}, "unit_amount_decimal": KEEP},
        "price": _PRICE,  # older API versions
        "parent": {"type": KEEP, "subscription_item_details": {"proration": KEEP}},
    }},
    "payments": {"data": {"payment": {"payment_intent": ID}}},
}

PROJECTIONS: dict[str, Spec] = {
    "payment_intent": {
        "id": KEEP, "object": KEEP, "created": KEEP, "status": KEEP, "amount": KEEP, "currency": KEEP,
        "amount_received": KEEP, "application_fee_amount": KEEP, "canceled_at": KEEP, "cancellation_reason": KEEP,
        "payment_method_types": KEEP, "livemode": KEEP,
        "description": KEEP, "receipt_email": SEAL, "customer": ID,
        "application": ID,  # the Connect platform that created it (e.g. Substack): labels where a payment came from
        "last_payment_error": {"message": KEEP, "code": KEEP, "decline_code": KEEP, "type": KEEP},
        "latest_charge": {
            "id": KEEP, "object": KEEP, "created": KEEP, "currency": KEEP, "amount": KEEP,
            "amount_captured": KEEP, "amount_refunded": KEEP, "captured": KEEP, "paid": KEEP, "refunded": KEEP,
            "disputed": KEEP, "status": KEEP, "failure_code": KEEP,
            "application": ID,
            "receipt_email": SEAL, "billing_details": {"email": SEAL},  # never the cardholder's name or address
            # How they paid, never which card: no last4, fingerprint, expiry or cardholder.
            "payment_method_details": {
                "type": KEEP,
                "card": {"brand": KEEP, "funding": KEEP, "country": KEEP, "wallet": {"type": KEEP}},
            },
            "outcome": {"network_status": KEEP, "reason": KEEP, "risk_level": KEEP, "risk_score": KEEP, "type": KEEP},
            "balance_transaction": {
                "id": KEEP, "currency": KEEP, "amount": KEEP, "exchange_rate": KEEP, "available_on": KEEP,
                "fee_details": {"type": KEEP, "description": KEEP, "amount": KEEP},
            },
            "refunds": {"data": {"created": KEEP, "amount": KEEP, "status": KEEP, "reason": KEEP, "currency": KEEP}},
            "dispute": {
                "id": KEEP, "created": KEEP, "status": KEEP, "reason": KEEP, "amount": KEEP, "currency": KEEP,
                "is_charge_refundable": KEEP,
                # Only when evidence is due and whether it was sent: never the evidence itself.
                "evidence_details": {"due_by": KEEP, "has_evidence": KEEP, "past_due": KEEP, "submission_count": KEEP},
                "balance_transactions": {"created": KEEP, "amount": KEEP, "fee": KEEP},
            },
        },
    },
    "invoice": _INVOICE,
    "subscription": {
        "id": KEEP, "object": KEEP, "created": KEEP, "status": KEEP, "start_date": KEEP,
        "canceled_at": KEEP, "ended_at": KEEP, "cancel_at": KEEP, "cancel_at_period_end": KEEP, "customer": ID,
        "cancellation_details": {"reason": KEEP, "feedback": KEEP},  # not "comment": the customer's own words
        "collection_method": KEEP, "billing_cycle_anchor": KEEP, "trial_start": KEEP, "trial_end": KEEP,
        "current_period_start": KEEP, "current_period_end": KEEP,  # older API versions; newer: on each item
        "pause_collection": {"behavior": KEEP, "resumes_at": KEEP},
        "discount": _DISCOUNT,  # older API versions
        "discounts": ID,
        # The price tells plans apart (e.g. Founding) and monthly from yearly billing.
        "items": {"data": {
            "quantity": KEEP, "current_period_start": KEEP, "current_period_end": KEEP, "price": _PRICE,
        }},
        "latest_invoice": _INVOICE,
    },
    "customer": {
        "id": KEEP, "object": KEEP, "created": KEEP, "deleted": KEEP, "email": SEAL,
        "name": SEAL,  # for greeting them by first name in notes (app/templates.py)
        "currency": KEEP, "delinquent": KEEP, "preferred_locales": KEEP,
    },
}


def _seal(value: str, key: bytes) -> str:
    return SEALED_PREFIX + base64.urlsafe_b64encode(aead_seal(key, value.encode(), _AAD)).decode()


def _project(value: Any, spec: Any, key: bytes) -> Any:
    if value is None:
        return None
    if spec == KEEP:
        return value
    if spec == SEAL:
        return _seal(value, key) if isinstance(value, str) else None
    if spec == ID:
        return value.get("id") if isinstance(value, dict) else value
    if isinstance(value, list):
        return [_project(v, spec, key) for v in value]
    if isinstance(value, dict):
        return {k: _project(value[k], s, key) for k, s in spec.items() if k in value}
    # A nested spec over a scalar: an unexpanded reference (its id), which is safe to keep.
    return value if isinstance(value, str) else None


def project(obj_type: str, obj: dict, key: bytes) -> dict:
    """The stored form of a Stripe object: only allowlisted fields, with emails encrypted under `key`."""
    return _project(obj, PROJECTIONS[obj_type], key)


def unseal(data: Any, key: bytes) -> Any:
    """A stored object with its emails decrypted, ready for the normalizers."""
    if isinstance(data, str) and data.startswith(SEALED_PREFIX):
        try:
            return aead_open(key, base64.urlsafe_b64decode(data[len(SEALED_PREFIX):]), _AAD).decode()
        except DecryptionError:
            return None
    if isinstance(data, dict):
        return {k: unseal(v, key) for k, v in data.items()}
    if isinstance(data, list):
        return [unseal(v, key) for v in data]
    return data
