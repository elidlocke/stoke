"""Register the webhook endpoint that keeps stored Stripe objects current.

One "connected accounts" endpoint on the Stripe App's own Stripe account receives events from every
account that installed the app, and tells Stoke when it's uninstalled. It's created at the API version
Stoke pins, though only the event's type and ids are read: the sync worker re-reads each changed object
(see app/sync.py).

    cd backend
    uv run python scripts/register_webhook.py --url https://stoke-y4sf.onrender.com/api/stripe/webhook

Uses STRIPE_APP_SECRET_KEY (a test key registers a test-mode endpoint), so the endpoint can't land on a
writer's account. Set the printed signing secret as STRIPE_WEBHOOK_SECRET. For
local development, `stripe listen --all-snapshot --forward-connect-to localhost:8000/api/stripe/webhook`, logged in to the
app's account, prints a secret to use instead.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.stripe_client import STRIPE_API_VERSION, account_name, make_client  # noqa: E402

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
    # The Stripe App was uninstalled: its credentials for that account stop working.
    "account.application.deauthorized",
]


async def main(url: str) -> int:
    key = os.environ.get("STRIPE_APP_SECRET_KEY")
    if not key:
        print("Set STRIPE_APP_SECRET_KEY in .env to the secret key of the Stripe App's own account.")
        return 1
    client = make_client(key)  # async only, like the app's
    account = (await client.v1.accounts.retrieve_current_async()).to_dict()
    endpoint = await client.v1.webhook_endpoints.create_async({
        "url": url,
        "connect": True,
        "api_version": STRIPE_API_VERSION,
        "enabled_events": EVENTS,
        "description": "Stoke: keep stored Stripe objects current",
    })
    print(f"Created {endpoint.id} on {account_name(account)} ({account['id']}) for {url} at API version {STRIPE_API_VERSION}.")
    print(f"Set STRIPE_WEBHOOK_SECRET={endpoint.secret}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True, help="the endpoint, ending in /api/stripe/webhook")
    sys.exit(asyncio.run(main(parser.parse_args().url)))
