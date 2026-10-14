from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import gmail
from app.auth import UserDep
from app.config import get_settings
from app.db import get_session
from app.db_models import GmailConnection
from app.models import GmailConnectOut, GmailOut

router = APIRouter(prefix="/api/gmail")

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Holds the connect flow's nonce while the writer is at Google, so the callback knows it's the same browser.
# Lax: sent on Google's top-level redirect back. Scoped to these routes; the frontend's scripts never see it.
NONCE_COOKIE = "stoke_gmail_flow"
COOKIE_PATH = "/api/gmail"


def _out(conn: GmailConnection | None) -> GmailOut:
    return GmailOut(
        available=gmail.configured(),
        email=conn.email if conn else None,
        status=conn.status if conn else None,
        connected_at=int(conn.updated_at.timestamp()) if conn else None,
        last_sent_at=int(conn.last_sent_at.timestamp()) if conn and conn.last_sent_at else None,
    )


@router.get("")
async def get_gmail(user: UserDep, session: SessionDep) -> GmailOut:
    """Whether the writer's Gmail is connected, and which address."""
    return _out(await gmail.connection(session, user))


@router.post("/connect")
async def start_connect(user: UserDep, response: Response) -> GmailConnectOut:
    """Google's consent page, for the frontend to send the writer to."""
    url, nonce = gmail.authorization_url(user)
    response.set_cookie(
        NONCE_COOKIE, nonce, max_age=gmail.STATE_TTL_SECONDS, path=COOKIE_PATH, httponly=True, samesite="lax",
        secure=get_settings().cors_origin.startswith("https://"),
    )
    return GmailConnectOut(url=url)


@router.get("/callback", include_in_schema=False)
async def finish_connect(
    session: SessionDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    nonce: Annotated[str | None, Cookie(alias=NONCE_COOKIE)] = None,
) -> RedirectResponse:
    """Where Google sends the writer back: stores the connection, then on to Settings with the outcome as
    ?gmail=connected, or a reason it failed (app/gmail.py). Never a parameter named code, state or error,
    which the frontend's Auth0 SDK would take for its own."""
    if error:
        outcome = "denied" if error == "access_denied" else "failed"
    elif not code or not state:
        outcome = "failed"
    else:
        try:
            await gmail.connect(session, code, state, nonce)
            outcome = "connected"
        except gmail.GmailError as exc:
            outcome = exc.reason
    redirect = RedirectResponse(f"/settings?gmail={outcome}#gmail", status_code=303)
    redirect.delete_cookie(NONCE_COOKIE, path=COOKIE_PATH)
    return redirect


@router.delete("", status_code=204)
async def disconnect(user: UserDep, session: SessionDep) -> Response:
    """Revokes Stoke's access to the writer's Gmail and forgets the token."""
    await gmail.disconnect(session, user)
    return Response(status_code=204)
