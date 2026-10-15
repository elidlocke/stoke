"""A user's connected Stripe accounts: checked against Stripe when connected, with the secret kept only encrypted.

Accounts are connected by installing Stoke's Stripe App (app/stripe_app.py); the stored secret is its refresh
token. Accounts added earlier with a restricted key keep working until they're switched to the app, which
converts them in place.

Every lookup is filtered by the owner, so another user's credential id behaves like a missing one.
The plaintext secret exists only in memory: while it's checked here, and in the Stripe client built
from it (see stripe_client.get_scope). It's never logged and never returned.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import stripe
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import fetch, stripe_app, sync
from app.auth import CurrentUser
from app.crypto import get_cipher
from app.db_models import StripeCredential, credential_aad, credential_account_id
from app.stripe_client import account_name, clear_scope_cache, make_client

MAX_ACCOUNTS_PER_USER = 50

# What the views read, each checked with a one-item list. "Accounts" (for the name) is checked separately.
PERMISSION_CHECKS = {
    "PaymentIntents": lambda c: c.v1.payment_intents.list_async({"limit": 1}),
    "Invoices": lambda c: c.v1.invoices.list_async({"limit": 1}),
    "Charges": lambda c: c.v1.charges.list_async({"limit": 1}),
    "Customers": lambda c: c.v1.customers.list_async({"limit": 1}),
    "Subscriptions": lambda c: c.v1.subscriptions.list_async({"limit": 1}),
    "Balance transactions": lambda c: c.v1.balance_transactions.list_async({"limit": 1}),
    # To catch up on changes since the last sync (see app/sync.py).
    "Events": lambda c: c.v1.events.list_async({"limit": 1}),
}


class CredentialError(Exception):
    """The account can't be connected or read; the message is safe to show the user."""


class InvalidKey(CredentialError):
    pass


class CredentialNotFound(Exception):
    pass


@dataclass(frozen=True)
class Probe:
    stripe_account_id: str | None
    display_name: str
    settlement_currency: str
    missing_permissions: list[str]


def _invalid() -> InvalidKey:
    return InvalidKey("Stripe didn't accept this key. Check it was copied in full and hasn't been rolled or deleted.")


async def probe(raw: str) -> Probe:
    """Which account the key belongs to, and which of the permissions Stoke needs it lacks."""
    client = make_client(raw)
    missing: list[str] = []
    try:
        account: dict | None = (await client.v1.accounts.retrieve_current_async()).to_dict()
    except stripe.AuthenticationError:
        raise _invalid() from None
    except stripe.PermissionError:
        account = None
        missing.append("Accounts")

    results = await asyncio.gather(*(check(client) for check in PERMISSION_CHECKS.values()), return_exceptions=True)
    balance_currency = None
    for name, result in zip(PERMISSION_CHECKS, results):
        if isinstance(result, stripe.PermissionError):
            missing.append(name)
        elif isinstance(result, stripe.AuthenticationError):
            raise _invalid() from None
        elif isinstance(result, BaseException):
            raise result
        elif name == "Balance transactions" and result.data:
            balance_currency = result.data[0].currency

    if account is not None:
        return Probe(
            stripe_account_id=account["id"],
            display_name=account_name(account),
            settlement_currency=(account.get("default_currency") or balance_currency or "usd").lower(),
            missing_permissions=missing,
        )
    # Without "Accounts: Read" the account is unnamed, and its payout currency is taken from its balance history.
    return Probe(None, "Stripe account", (balance_currency or "usd").lower(), missing)


def _status(p: Probe) -> str:
    return "missing_permissions" if p.missing_permissions else "ok"


async def list_for_user(session: AsyncSession, user: CurrentUser) -> list[StripeCredential]:
    return list(await session.scalars(
        select(StripeCredential).where(StripeCredential.user_id == user.id).order_by(StripeCredential.created_at)
    ))


async def get_for_user(session: AsyncSession, user: CurrentUser, credential_id: uuid.UUID) -> StripeCredential:
    cred = await session.scalar(
        select(StripeCredential).where(StripeCredential.id == credential_id, StripeCredential.user_id == user.id)
    )
    if cred is None:
        raise CredentialNotFound(credential_id)
    return cred


async def _commit(session: AsyncSession, user: CurrentUser) -> None:
    await session.commit()
    clear_scope_cache(user.id)


async def connect_app(session: AsyncSession, code: str, state: str, browser_nonce: str | None) -> StripeCredential:
    """Finishes the Stripe App install `stripe_app.authorization_url` started, for the user who started it.

    Connecting an account the user already has (a key-based one, or the app again) updates that record in place,
    so its name and the links paid through it are kept.
    """
    user_id = stripe_app.check_state(state, browser_nonce)
    tokens = await stripe_app.exchange_code(code)
    try:
        p = await probe(tokens.access_token)
    except InvalidKey:
        raise stripe_app.StripeAppError("Stripe didn't let Stoke read that account. Try connecting again.") from None

    cred = await session.scalar(select(StripeCredential).where(
        StripeCredential.user_id == user_id, StripeCredential.stripe_account_id == tokens.account_id
    ))
    previous = None
    if cred is None:
        count = await session.scalar(select(func.count()).where(StripeCredential.user_id == user_id))
        if (count or 0) >= MAX_ACCOUNTS_PER_USER:
            raise stripe_app.StripeAppError(f"You can connect up to {MAX_ACCOUNTS_PER_USER} accounts.", "too_many")
        cred = StripeCredential(id=uuid.uuid4(), user_id=user_id)
        session.add(cred)
    else:
        previous = (credential_account_id(cred), cred.livemode)
    await stripe_app.seal(cred, tokens.refresh_token)
    cred.key_type, cred.key_last4, cred.livemode = "oauth", None, tokens.livemode
    cred.stripe_account_id = tokens.account_id  # from Stripe's token response: known without "Accounts: Read"
    cred.display_name, cred.settlement_currency = p.display_name, p.settlement_currency
    cred.status, cred.missing_permissions = _status(p), p.missing_permissions
    cred.last_verified_at = datetime.now(UTC)
    try:
        await session.commit()
    except IntegrityError:  # the unique (user, account) constraint, if two connects race
        await session.rollback()
        raise stripe_app.StripeAppError("That Stripe account is already connected.") from None
    clear_scope_cache(user_id)
    fetch.clear_credential(cred.id)
    stripe_app.remember(cred.id, tokens.access_token)
    await start_sync(cred, previous)
    return cred


async def start_sync(cred: StripeCredential, previous: tuple[str, bool] | None = None) -> None:
    """Import the key's account, or the parts of it the key can newly read (see app/sync.py).

    `previous` is the account the key read before a change: once a key can name its account, or a
    test key is replaced by a live one, what was stored under the old one may no longer be needed.
    """
    if previous is not None and previous != (credential_account_id(cred), cred.livemode):
        await sync.forget_if_orphaned(*previous)
    if cred.status != "invalid":
        await sync.start_backfill(credential_account_id(cred), cred.livemode, cred.missing_permissions)


async def retry_sync(session: AsyncSession, user: CurrentUser, credential_id: uuid.UUID) -> StripeCredential:
    """Start a failed import again."""
    cred = await get_for_user(session, user, credential_id)
    await start_sync(cred)
    return cred


async def reimport(session: AsyncSession, user: CurrentUser, credential_id: uuid.UUID) -> StripeCredential:
    """Import the account's history again from the start, for when what's stored has fallen behind
    (e.g. Stripe's webhooks can't reach this server). What's stored is shown meanwhile."""
    cred = await get_for_user(session, user, credential_id)
    if cred.status == "invalid":
        raise CredentialError("Stripe no longer lets Stoke read this account. Reconnect it, then import again.")
    await sync.start_backfill(credential_account_id(cred), cred.livemode, cred.missing_permissions, restart=True)
    return cred


async def reverify(session: AsyncSession, user: CurrentUser, credential_id: uuid.UUID) -> StripeCredential:
    """Check a stored connection again, e.g. after granting a key more permissions in Stripe."""
    cred = await get_for_user(session, user, credential_id)
    previous = (credential_account_id(cred), cred.livemode)
    try:
        if cred.is_app:
            raw = await stripe_app.access_token(cred)
        else:
            raw = await get_cipher().decrypt(cred.sealed, credential_aad(user.id, cred.id))
        p = await probe(raw)
    except (InvalidKey, stripe_app.AppDisconnected):
        cred.status, cred.missing_permissions = "invalid", []
    else:
        cred.status, cred.missing_permissions = _status(p), p.missing_permissions
        cred.display_name, cred.settlement_currency = p.display_name, p.settlement_currency
        cred.stripe_account_id = cred.stripe_account_id or p.stripe_account_id
    cred.last_verified_at = datetime.now(UTC)
    await _commit(session, user)
    fetch.clear_credential(cred.id)
    await start_sync(cred, previous)
    return cred


async def rename(session: AsyncSession, user: CurrentUser, credential_id: uuid.UUID, label: str | None) -> StripeCredential:
    cred = await get_for_user(session, user, credential_id)
    cred.label = label or None
    await _commit(session, user)
    return cred


async def delete(session: AsyncSession, user: CurrentUser, credential_id: uuid.UUID) -> None:
    cred = await get_for_user(session, user, credential_id)
    account_id, livemode = credential_account_id(cred), cred.livemode
    await session.delete(cred)
    await _commit(session, user)
    fetch.clear_credential(credential_id)
    stripe_app.forget(credential_id)
    # Stored customer data is kept only while someone has a key to the account.
    await sync.forget_if_orphaned(account_id, livemode)
