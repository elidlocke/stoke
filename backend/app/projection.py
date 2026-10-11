"""What Stoke stores of each Stripe object: an allowlist of fields, kept in Stripe's own shape.

A stored object is the API object with every field not listed here removed, so the normalizers in
app/aggregate.py read it exactly as they read a live one. A field Stripe adds in a new API version
is dropped until it's listed. Names, addresses, phone numbers, card details, metadata and dispute
evidence are never listed.

Email addresses are the only personal data kept: Stoke identifies customers by them. They're stored
encrypted ("enc:v1:…") under the account's own data key (see app/sync.py), and decrypted on read.

Changing a projection changes what's stored: bump PROJECTION_REV, then run scripts/resync.py.
"""

import base64
from typing import Any

from app.crypto import DecryptionError, aead_open, aead_seal

PROJECTION_REV = 1

KEEP = "keep"  # the value as is
SEAL = "seal"  # an email address: stored encrypted
ID = "id"  # an expandable reference: only its id, even if Stripe returned the expanded object

SEALED_PREFIX = "enc:v1:"
_AAD = b"stoke:stripe-email"

Spec = dict[str, Any]

_INVOICE: Spec = {
    "id": KEEP, "object": KEEP, "created": KEEP, "status": KEEP, "currency": KEEP,
    "customer_email": SEAL,  # a snapshot that survives the customer's deletion
    "billing_reason": KEEP, "attempt_count": KEEP, "amount_due": KEEP, "next_payment_attempt": KEEP,
    "subscription": ID,  # older API versions
    "parent": {"subscription_details": {"subscription": ID}},
    "lines": {"data": {
        "description": KEEP, "amount": KEEP, "proration": KEEP,
        "parent": {"subscription_item_details": {"proration": KEEP}},
    }},
    "payments": {"data": {"payment": {"payment_intent": ID}}},
}

PROJECTIONS: dict[str, Spec] = {
    "payment_intent": {
        "id": KEEP, "object": KEEP, "created": KEEP, "status": KEEP, "amount": KEEP, "currency": KEEP,
        "description": KEEP, "receipt_email": SEAL, "customer": ID,
        "last_payment_error": {"message": KEEP},
        "latest_charge": {
            "id": KEEP, "object": KEEP, "currency": KEEP, "amount_captured": KEEP, "amount_refunded": KEEP,
            "receipt_email": SEAL, "billing_details": {"email": SEAL},
            "balance_transaction": {
                "id": KEEP, "currency": KEEP, "amount": KEEP,
                "fee_details": {"type": KEEP, "description": KEEP, "amount": KEEP},
            },
            "refunds": {"data": {"created": KEEP, "amount": KEEP, "status": KEEP}},
            "dispute": {
                "id": KEEP, "created": KEEP, "status": KEEP, "reason": KEEP, "amount": KEEP,
                "evidence_details": {"due_by": KEEP},
                "balance_transactions": {"created": KEEP, "amount": KEEP, "fee": KEEP},
            },
        },
    },
    "invoice": _INVOICE,
    "subscription": {
        "id": KEEP, "object": KEEP, "created": KEEP, "status": KEEP, "start_date": KEEP,
        "canceled_at": KEEP, "ended_at": KEEP, "cancel_at": KEEP, "customer": ID,
        "cancellation_details": {"reason": KEEP, "feedback": KEEP},  # not "comment": the customer's own words
        "items": {"data": {"price": {"nickname": KEEP}}},
        "latest_invoice": _INVOICE,
    },
    "customer": {"id": KEEP, "object": KEEP, "created": KEEP, "deleted": KEEP, "email": SEAL},
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
