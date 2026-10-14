import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import credentials, links, profile, service, sync
from app.auth import UserDep
from app.db import get_session
from app.db_models import StripeCredential, UserSettings, WriterLink, credential_account_id
from app.models import (
    AddCredentialRequest,
    CredentialOut,
    CredentialsResponse,
    LinkIn,
    LinkOut,
    LinksResponse,
    MeResponse,
    PaymentSourceLabelIn,
    PaymentSourcesResponse,
    PlanLabelIn,
    PlansResponse,
    RenameCredentialRequest,
    ReplaceKeyRequest,
    UserSettingsIn,
    UserSettingsOut,
)
from app.stripe_client import clear_scope_cache

router = APIRouter(prefix="/api")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _sync_states(creds: list[StripeCredential]) -> dict[str, str]:
    keys = {str(c.id): (credential_account_id(c), c.livemode) for c in creds}
    states = await sync.progress(keys.values())
    return {cid: states[k].state for cid, k in keys.items()}


async def _out(c: StripeCredential) -> CredentialOut:
    return _to_out(c, (await _sync_states([c]))[str(c.id)])


def _to_out(c: StripeCredential, sync_state: str) -> CredentialOut:
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
        sync_state=sync_state,
    )


@router.get("/me")
async def get_me(user: UserDep) -> MeResponse:
    return MeResponse(email=user.email)


@router.get("/credentials")
async def list_credentials(user: UserDep, session: SessionDep) -> CredentialsResponse:
    creds = await credentials.list_for_user(session, user)
    states = await _sync_states(creds)
    return CredentialsResponse(credentials=[_to_out(c, states[str(c.id)]) for c in creds])


@router.post("/credentials", status_code=201)
async def add_credential(body: AddCredentialRequest, user: UserDep, session: SessionDep) -> CredentialOut:
    cred = await credentials.add(session, user, body.key.get_secret_value(), body.label)
    await session.refresh(cred)  # server-set timestamps
    return await _out(cred)


@router.put("/credentials/{credential_id}/key")
async def replace_credential_key(
    credential_id: uuid.UUID, body: ReplaceKeyRequest, user: UserDep, session: SessionDep
) -> CredentialOut:
    cred = await credentials.replace_key(session, user, credential_id, body.key.get_secret_value())
    await session.refresh(cred)
    return await _out(cred)


@router.patch("/credentials/{credential_id}")
async def rename_credential(
    credential_id: uuid.UUID, body: RenameCredentialRequest, user: UserDep, session: SessionDep
) -> CredentialOut:
    cred = await credentials.rename(session, user, credential_id, body.label)
    await session.refresh(cred)
    return await _out(cred)


@router.post("/credentials/{credential_id}/verify")
async def verify_credential(credential_id: uuid.UUID, user: UserDep, session: SessionDep) -> CredentialOut:
    cred = await credentials.reverify(session, user, credential_id)
    await session.refresh(cred)
    return await _out(cred)


@router.post("/credentials/{credential_id}/sync")
async def retry_credential_sync(credential_id: uuid.UUID, user: UserDep, session: SessionDep) -> CredentialOut:
    cred = await credentials.retry_sync(session, user, credential_id)
    return await _out(cred)

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


def _link_out(link: WriterLink) -> LinkOut:
    return LinkOut(
        id=str(link.id),
        category=link.category,
        kind=link.kind,
        name=link.name,
        url=link.url,
        paid_via_account_id=link.paid_via_account_id,
        purchase=link.purchase,
        created_at=int(link.created_at.timestamp()),
    )


@router.get("/links")
async def list_links(user: UserDep, session: SessionDep) -> LinksResponse:
    return LinksResponse(links=[_link_out(link) for link in await links.list_for_user(session, user)])


@router.post("/links", status_code=201)
async def add_link(body: LinkIn, user: UserDep, session: SessionDep) -> LinkOut:
    link = await links.add(session, user, body)
    await session.refresh(link)  # server-set timestamps
    return _link_out(link)


@router.put("/links/{link_id}")
async def update_link(link_id: uuid.UUID, body: LinkIn, user: UserDep, session: SessionDep) -> LinkOut:
    link = await links.update(session, user, link_id, body)
    await session.refresh(link)
    return _link_out(link)


@router.delete("/links/{link_id}", status_code=204)
async def delete_link(link_id: uuid.UUID, user: UserDep, session: SessionDep) -> Response:
    await links.delete(session, user, link_id)
    return Response(status_code=204)


RefPath = Annotated[str, Path(pattern=r"^[0-9a-f]{24}$")]


@router.get("/plans")
async def list_plans(user: UserDep, session: SessionDep) -> PlansResponse:
    """The writer's subscription plans, each labeled standard or Founding (confirmed, or Stoke's guess)."""
    return await service.plans(user, await profile.labels(session, user))


@router.put("/plans/{plan_id}", status_code=204)
async def label_plan(plan_id: RefPath, body: PlanLabelIn, user: UserDep, session: SessionDep) -> Response:
    try:
        price = await service.price_id(user, plan_id)
    except service.UnknownRef:
        raise HTTPException(404, "Not found")
    await profile.set_plan_label(session, user, price, body.label)
    return Response(status_code=204)


@router.get("/payment-sources")
async def list_payment_sources(user: UserDep, session: SessionDep) -> PaymentSourcesResponse:
    """The platforms that take payments into the writer's accounts, and what each one sells."""
    return await service.payment_sources(user, await links.revenue_sources(session, user), await profile.labels(session, user))


@router.put("/payment-sources/{source_id}", status_code=204)
async def label_payment_source(
    source_id: RefPath, body: PaymentSourceLabelIn, user: UserDep, session: SessionDep
) -> Response:
    try:
        app_id = await service.application_id(user, source_id)
    except service.UnknownRef:
        raise HTTPException(404, "Not found")
    await profile.set_application_label(session, user, app_id, body.label, await links.revenue_sources(session, user))
    return Response(status_code=204)
