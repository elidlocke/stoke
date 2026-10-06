import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import credentials
from app.auth import UserDep
from app.db import get_session
from app.db_models import StripeCredential, UserSettings
from app.models import (
    AddCredentialRequest,
    CredentialOut,
    CredentialsResponse,
    MeResponse,
    RenameCredentialRequest,
    ReplaceKeyRequest,
    UserSettingsIn,
    UserSettingsOut,
)
from app.stripe_client import clear_scope_cache

router = APIRouter(prefix="/api")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _out(c: StripeCredential) -> CredentialOut:
    return CredentialOut(
        id=str(c.id),
        label=c.label,
        stripe_account_id=c.stripe_account_id,
        display_name=c.display_name,
        settlement_currency=c.settlement_currency,
        livemode=c.livemode,
        key_type=c.key_type,
        key_last4=c.key_last4,
        status=c.status,
        missing_permissions=c.missing_permissions,
        created_at=int(c.created_at.timestamp()),
        last_verified_at=int(c.last_verified_at.timestamp()),
    )


@router.get("/me")
async def get_me(user: UserDep) -> MeResponse:
    return MeResponse(email=user.email)


@router.get("/credentials")
async def list_credentials(user: UserDep, session: SessionDep) -> CredentialsResponse:
    return CredentialsResponse(credentials=[_out(c) for c in await credentials.list_for_user(session, user)])


@router.post("/credentials", status_code=201)
async def add_credential(body: AddCredentialRequest, user: UserDep, session: SessionDep) -> CredentialOut:
    cred = await credentials.add(session, user, body.key.get_secret_value(), body.label)
    await session.refresh(cred)  # server-set timestamps
    return _out(cred)


@router.put("/credentials/{credential_id}/key")
async def replace_credential_key(
    credential_id: uuid.UUID, body: ReplaceKeyRequest, user: UserDep, session: SessionDep
) -> CredentialOut:
    cred = await credentials.replace_key(session, user, credential_id, body.key.get_secret_value())
    await session.refresh(cred)
    return _out(cred)


@router.patch("/credentials/{credential_id}")
async def rename_credential(
    credential_id: uuid.UUID, body: RenameCredentialRequest, user: UserDep, session: SessionDep
) -> CredentialOut:
    cred = await credentials.rename(session, user, credential_id, body.label)
    await session.refresh(cred)
    return _out(cred)


@router.post("/credentials/{credential_id}/verify")
async def verify_credential(credential_id: uuid.UUID, user: UserDep, session: SessionDep) -> CredentialOut:
    cred = await credentials.reverify(session, user, credential_id)
    await session.refresh(cred)
    return _out(cred)


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_credential(credential_id: uuid.UUID, user: UserDep, session: SessionDep) -> Response:
    await credentials.delete(session, user, credential_id)
    return Response(status_code=204)


@router.get("/settings")
async def get_user_settings(user: UserDep, session: SessionDep) -> UserSettingsOut:
    prefs = await session.get(UserSettings, user.id)
    return UserSettingsOut(reporting_currency=prefs.reporting_currency if prefs else None)


@router.put("/settings")
async def put_user_settings(body: UserSettingsIn, user: UserDep, session: SessionDep) -> UserSettingsOut:
    currency = body.reporting_currency.lower() if body.reporting_currency else None
    await session.merge(UserSettings(user_id=user.id, reporting_currency=currency))
    await session.commit()
    clear_scope_cache(user.id)
    return UserSettingsOut(reporting_currency=currency)
