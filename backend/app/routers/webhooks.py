"""Stripe webhooks from the accounts that installed Stoke's Stripe App (and, in development, the Connect
platform's connected accounts). Each event only says which object changed; the sync worker re-reads it
from Stripe (see app/sync.py). An uninstall disconnects the account's app credentials."""

import stripe
from fastapi import APIRouter, HTTPException, Request

from app import stripe_app, sync
from app.config import get_settings
from app.stripe_client import clear_scope_cache

router = APIRouter(prefix="/api/stripe")


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request) -> dict:
    secret = get_settings().stripe_webhook_secret
    if secret is None or not secret.get_secret_value():
        raise HTTPException(404)
    try:
        event = stripe.Webhook.construct_event(
            await request.body(), request.headers.get("stripe-signature"), secret.get_secret_value()
        )
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Invalid signature")
    data = event.to_dict()
    if _is_uninstall(data):
        for user_id in await stripe_app.uninstalled(data["account"], bool(data.get("livemode"))):
            clear_scope_cache(user_id)
        sync._accounts.clear()
    else:
        await sync.handle_event(data)
    return {"received": True}


def _is_uninstall(event: dict) -> bool:
    """Stoke's Stripe App was uninstalled from the event's account (not some other app or Connect platform)."""
    app = ((event.get("data") or {}).get("object") or {}).get("id")
    return (
        event.get("type") == "account.application.deauthorized" and bool(event.get("account"))
        and app is not None and app == stripe_app.client_id()
    )
