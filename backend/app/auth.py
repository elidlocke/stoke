"""Who's calling: verifies the Auth0 access token on each request and maps it to a local user.

The frontend signs in with Auth0 and sends `Authorization: Bearer <access token>`. The token is an
RS256 JWT issued for our API (the audience). It's checked against the tenant's published signing
keys (JWKS): signature, issuer, audience and expiry. Access tokens carry no email by default, so an
Auth0 Post-Login Action adds it as the EMAIL_CLAIM custom claim (see the README).

A bearer header, unlike a cookie, isn't sent automatically by the browser, so there's no CSRF.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, Header
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.db_models import User

EMAIL_CLAIM = "https://stoke/email"
JWKS_TTL_SECONDS = 600
LEEWAY_SECONDS = 30


class Unauthenticated(Exception):
    pass


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    auth_subject: str
    email: str | None


_jwks: tuple[float, jwt.PyJWKSet] | None = None


def clear_jwks_cache() -> None:
    global _jwks
    _jwks = None


async def _jwks_set(force: bool = False) -> jwt.PyJWKSet:
    global _jwks
    if _jwks is None or force or time.monotonic() - _jwks[0] > JWKS_TTL_SECONDS:
        url = f"https://{get_settings().auth0_domain}/.well-known/jwks.json"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        _jwks = (time.monotonic(), jwt.PyJWKSet.from_dict(resp.json()))
    return _jwks[1]


async def _signing_key(kid: str) -> jwt.PyJWK:
    for force in (False, True):  # an unknown kid may mean Auth0 rotated its keys: refetch once
        for key in (await _jwks_set(force)).keys:
            if key.key_id == kid:
                return key
    raise Unauthenticated("Unknown signing key")


async def verify_token(token: str) -> dict:
    settings = get_settings()
    if not settings.auth0_domain or not settings.auth0_audience:
        raise RuntimeError("Set AUTH0_DOMAIN and AUTH0_AUDIENCE")
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise Unauthenticated("Unexpected token type")
        key = await _signing_key(header["kid"])
        return jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=settings.auth0_audience,
            issuer=f"https://{settings.auth0_domain}/",
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise Unauthenticated("Invalid token") from exc


async def current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthenticated("Missing bearer token")
    claims = await verify_token(token)
    email = claims.get(EMAIL_CLAIM)
    email = email.strip().lower() if isinstance(email, str) and email.strip() else None

    # First sight of this Auth0 user creates them; later requests refresh last_seen_at and email.
    stmt = (
        insert(User)
        .values(id=uuid.uuid4(), auth_subject=claims["sub"], email=email)
        .on_conflict_do_update(
            index_elements=[User.auth_subject],
            set_={"last_seen_at": func.now(), "email": func.coalesce(email, User.email)},
        )
        .returning(User.id)
    )
    user_id = (await session.execute(stmt)).scalar_one()
    await session.commit()
    return CurrentUser(id=user_id, auth_subject=claims["sub"], email=email)


UserDep = Annotated[CurrentUser, Depends(current_user)]
