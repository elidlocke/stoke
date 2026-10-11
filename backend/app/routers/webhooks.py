"""Stripe webhooks from connected accounts. Each event only says which object changed; the sync
worker re-reads it from Stripe (see app/sync.py)."""

import stripe
from fastapi import APIRouter, HTTPException, Request

from app import sync
from app.config import get_settings

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
    await sync.handle_event(event.to_dict())
    return {"received": True}
