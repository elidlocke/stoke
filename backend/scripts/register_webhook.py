"""Register the Connect webhook endpoint that keeps stored Stripe objects current.

One endpoint on the platform's own Stripe account receives events from every connected account.
It's created at the API version Stoke pins, though only the event's type and ids are read: the
sync worker re-reads each changed object (see app/sync.py).

    cd backend
    uv run python scripts/register_webhook.py --url https://stoke-y4sf.onrender.com/api/stripe/webhook

Uses STRIPE_PLATFORM_KEY (a test key registers a test-mode endpoint). Set the printed signing secret
as STRIPE_WEBHOOK_SECRET. For local development, `stripe listen --forward-connect-to
localhost:8000/api/stripe/webhook` prints a secret to use instead.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.stripe_client import STRIPE_API_VERSION, make_client  # noqa: E402

# Everything that changes a stored payment intent, invoice, subscription or customer.
EVENTS = [
    *(f"payment_intent.{e}" for e in (
        "created", "succeeded", "processing", "payment_failed", "canceled", "requires_action",
        "amount_capturable_updated",
    )),
    *(f"charge.{e}" for e in ("succeeded", "failed", "pending", "captured", "expired", "refunded", "updated")),
    "charge.refund.updated",
    *(f"refund.{e}" for e in ("created", "updated", "failed")),
    *(f"charge.dispute.{e}" for e in ("created", "updated", "closed", "funds_withdrawn", "funds_reinstated")),
    *(f"invoice.{e}" for e in (
        "created", "deleted", "finalized", "paid", "payment_failed", "payment_succeeded",
        "payment_action_required", "marked_uncollectible", "voided", "updated",
    )),
    "invoice_payment.paid",
    *(f"customer.subscription.{e}" for e in (
        "created", "updated", "deleted", "paused", "resumed", "trial_will_end",
        "pending_update_applied", "pending_update_expired",
    )),
    *(f"customer.{e}" for e in ("created", "updated", "deleted")),
]


def main(url: str) -> int:
    key = os.environ.get("STRIPE_PLATFORM_KEY") or os.environ.get("STRIPE_API_KEY")
    if not key:
        print("Set STRIPE_PLATFORM_KEY in .env to the platform's secret key.")
        return 1
    endpoint = make_client(key).v1.webhook_endpoints.create({
        "url": url,
        "connect": True,
        "api_version": STRIPE_API_VERSION,
        "enabled_events": EVENTS,
        "description": "Stoke: keep stored Stripe objects current",
    })
    print(f"Created {endpoint.id} for {url} at API version {STRIPE_API_VERSION}.")
    print(f"Set STRIPE_WEBHOOK_SECRET={endpoint.secret}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True, help="the endpoint, ending in /api/stripe/webhook")
    sys.exit(main(parser.parse_args().url))
