import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import credentials, links, profile, service, stripe_app, substack, substack_list, sync
from app.auth import CurrentUser, UserDep
from app.db import get_session
from app.db_models import StripeCredential, UserSettings, WriterLink, credential_account_id
from app.models import (
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
    SubstackIn,
    SubstackListIn,
    SubstackListOut,
    SubstackOut,
    SubstackProfileOut,
    SubstackPublicationOut,
    UserSettingsIn,
    UserSettingsOut,
)
from app.stripe_client import clear_scope_cache

router = APIRouter(prefix="/api")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
PublicationPath = Annotated[str, Path(pattern=r"^[a-z0-9-]{1,63}$")]  # a subdomain on substack.com


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
    return CredentialsResponse(
        credentials=[_to_out(c, states[str(c.id)]) for c in creds], connect_available=stripe_app.configured()
    )


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

@router.post("/credentials/{credential_id}/reimport")
async def reimport_credential(credential_id: uuid.UUID, user: UserDep, session: SessionDep) -> CredentialOut:
    cred = await credentials.reimport(session, user, credential_id)
    return await _out(cred)


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_credential(credential_id: uuid.UUID, user: UserDep, session: SessionDep) -> Response:
    await credentials.delete(session, user, credential_id)
    return Response(status_code=204)


@router.get("/settings")
async def get_user_settings(user: UserDep, session: SessionDep) -> UserSettingsOut:
    prefs = await session.get(UserSettings, user.id)
    return UserSettingsOut(reporting_currency=prefs.reporting_currency if prefs else None)


async def _prefs(session: AsyncSession, user: CurrentUser) -> UserSettings:
    prefs = await session.get(UserSettings, user.id)
    if prefs is None:
        prefs = UserSettings(user_id=user.id)
        session.add(prefs)
    return prefs


@router.put("/settings")
async def put_user_settings(body: UserSettingsIn, user: UserDep, session: SessionDep) -> UserSettingsOut:
    currency = body.reporting_currency.lower() if body.reporting_currency else None
    (await _prefs(session, user)).reporting_currency = currency
    await session.commit()
    clear_scope_cache(user.id)
    return UserSettingsOut(reporting_currency=currency)


async def _substack_out(
    session: AsyncSession, user: CurrentUser, handle: str | None, refresh: bool = False
) -> SubstackOut:
    if handle is None:
        return SubstackOut(handle=None, profile=None, suggestions=[], publications=[], error=None)
    try:
        found = await substack.read(handle, refresh)
    except substack.NotFound:
        return SubstackOut(
            handle=handle, profile=None, suggestions=[], publications=[],
            error=f"No Substack profile found at @{handle}.",
        )
    except substack.Unavailable:
        return SubstackOut(
            handle=handle, profile=None, suggestions=[], publications=[], error=substack.UNAVAILABLE,
        )
    existing = [link.url for link in await links.list_for_user(session, user)]
    return SubstackOut(
        handle=handle,
        profile=SubstackProfileOut(name=found.name, photo_url=found.photo_url, url=found.url),
        suggestions=[s for s in found.links if not any(substack.same_link(s.url, url) for url in existing)],
        publications=[SubstackPublicationOut(subdomain=p.subdomain, name=p.name, url=p.url) for p in found.publications],
        error=None,
    )


@router.get("/substack")
async def get_substack(user: UserDep, session: SessionDep) -> SubstackOut:
    """The writer's Substack handle, and the links on their profile they haven't added yet."""
    prefs = await session.get(UserSettings, user.id)
    return await _substack_out(session, user, prefs.substack_handle if prefs else None)


@router.put("/substack")
async def put_substack(body: SubstackIn, user: UserDep, session: SessionDep) -> SubstackOut:
    handle = substack.parse_handle(body.handle) if body.handle else None
    if handle is not None:
        try:
            await substack.read(handle, refresh=True)  # saving again picks up profile changes
        except substack.NotFound:
            raise substack.SubstackError(f"No Substack profile found at @{handle}. Check the handle on your profile page.")
        except substack.Unavailable:
            pass  # saved anyway: it's read again next time
    (await _prefs(session, user)).substack_handle = handle
    await session.commit()
    return await _substack_out(session, user, handle)  # just read


def _list_out(row) -> SubstackListOut:
    return SubstackListOut(
        publication=row.publication, exported_at=int(row.exported_at.timestamp()), uploaded_at=int(row.uploaded_at.timestamp()),
        free_count=row.free_count,
    )


@router.get("/substack/subscribers")
async def get_substack_lists(user: UserDep, session: SessionDep) -> list[SubstackListOut]:
    """The writer's uploaded free subscribers, one list per publication: how many, and how fresh."""
    return [_list_out(row) for row in await substack_list.metas(session, user)]


@router.put("/substack/subscribers/{publication}")
async def put_substack_list(
    publication: PublicationPath, body: SubstackListIn, user: UserDep, session: SessionDep
) -> SubstackListOut:
    """Replaces the publication's free subscribers with those in its Substack export."""
    export = substack_list.parse(body.filename, body.csv)
    return _list_out(await substack_list.save(session, user, publication, export))


@router.delete("/substack/subscribers/{publication}", status_code=204)
async def delete_substack_list(publication: PublicationPath, user: UserDep, session: SessionDep) -> Response:
    await substack_list.delete(session, user, publication)
    return Response(status_code=204)


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
    """The writer's subscription plans, each with its label (confirmed, or Stoke's guess)."""
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
