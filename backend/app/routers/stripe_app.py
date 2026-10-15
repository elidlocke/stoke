from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import credentials, stripe_app
from app.auth import UserDep
from app.config import get_settings
from app.db import get_session
from app.models import StripeConnectOut

router = APIRouter(prefix="/api/stripe")

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Holds the install flow's nonce while the writer is at Stripe, so the callback knows it's the same browser
# (app/oauth_state.py). Lax: sent on Stripe's top-level redirect back. Scoped to the callback.
NONCE_COOKIE = "stoke_stripe_flow"
COOKIE_PATH = "/api/stripe/callback"


@router.post("/connect")
async def start_connect(user: UserDep, response: Response) -> StripeConnectOut:
    """The Stripe App's install page, for the frontend to send the writer to."""
    url, nonce = stripe_app.authorization_url(user)
    response.set_cookie(
        NONCE_COOKIE, nonce, max_age=stripe_app.STATE_TTL_SECONDS, path=COOKIE_PATH, httponly=True, samesite="lax",
        secure=get_settings().cors_origin.startswith("https://"),
    )
    return StripeConnectOut(url=url)


@router.get("/callback", include_in_schema=False)
async def finish_connect(
    session: SessionDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    nonce: Annotated[str | None, Cookie(alias=NONCE_COOKIE)] = None,
) -> RedirectResponse:
    """Where Stripe sends the writer back: stores the connection, then on to Settings with the outcome as
    ?stripe=connected, or a reason it failed (app/stripe_app.py). Never a parameter named code, state or error,
    which the frontend's Auth0 SDK would take for its own."""
    if error:
        outcome = "denied" if error == "access_denied" else "failed"
    elif not code or not state:
        outcome = "failed"
    else:
        try:
            await credentials.connect_app(session, code, state, nonce)
            outcome = "connected"
        except stripe_app.StripeAppError as exc:
            outcome = exc.reason
        except credentials.CredentialError:
            outcome = "failed"
    redirect = RedirectResponse(f"/settings?stripe={outcome}#stripe", status_code=303)
    redirect.delete_cookie(NONCE_COOKIE, path=COOKIE_PATH)
    return redirect
