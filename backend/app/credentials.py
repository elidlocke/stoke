"""A user's stored Stripe keys: validated against Stripe when added, then kept only encrypted.

Every lookup is filtered by the owner, so another user's credential id behaves like a missing one.
The plaintext key exists only in memory: while it's checked here, and in the Stripe client built
from it (see stripe_client.get_scope). It's never logged and never returned; the API shows its
last four characters.
"""

import asyncio
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import stripe
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import fetch
from app.auth import CurrentUser
from app.crypto import get_cipher
from app.db_models import StripeCredential, credential_aad
from app.stripe_client import account_name, clear_scope_cache, make_client

KEY_PATTERN = re.compile(r"^(rk|sk)_(test|live)_[A-Za-z0-9]{10,240}$")
MAX_KEYS_PER_USER = 50

# What the views read, each checked with a one-item list. "Accounts" (for the name) is checked separately.
PERMISSION_CHECKS = {
    "PaymentIntents": lambda c: c.v1.payment_intents.list_async({"limit": 1}),
    "Invoices": lambda c: c.v1.invoices.list_async({"limit": 1}),
    "Charges": lambda c: c.v1.charges.list_async({"limit": 1}),
    "Customers": lambda c: c.v1.customers.list_async({"limit": 1}),
    "Subscriptions": lambda c: c.v1.subscriptions.list_async({"limit": 1}),
    "Balance transactions": lambda c: c.v1.balance_transactions.list_async({"limit": 1}),
}


class CredentialError(Exception):
    """The key can't be used; the message is safe to show the user."""


class InvalidKey(CredentialError):
    pass


class DuplicateAccount(CredentialError):
    pass


class CredentialNotFound(Exception):
    pass


@dataclass(frozen=True)
class Probe:
    stripe_account_id: str | None
    display_name: str
    settlement_currency: str
    missing_permissions: list[str]


def check_format(raw: str) -> tuple[str, bool]:
    """(key_type, livemode) for a key that's acceptable to store; otherwise CredentialError."""
    if raw.startswith("pk_"):
        raise CredentialError("That's a publishable key. Use a restricted key (rk_…) with read access.")
    m = KEY_PATTERN.match(raw)
    if not m:
        raise CredentialError("That doesn't look like a Stripe API key. Restricted keys start with rk_live_ or rk_test_.")
    prefix, mode = m.groups()
    if prefix == "sk" and mode == "live":
        # A live secret key can move money. Stoke only reads, so it never needs one.
        raise CredentialError("Live secret keys aren't accepted. Create a restricted key with Read access instead.")
    return ("secret" if prefix == "sk" else "restricted"), mode == "live"


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


async def _check_not_duplicate(
    session: AsyncSession, user: CurrentUser, account_id: str | None, except_id: uuid.UUID | None = None
) -> None:
    if account_id is None:
        return
    q = select(StripeCredential.display_name).where(
        StripeCredential.user_id == user.id, StripeCredential.stripe_account_id == account_id
    )
    if except_id is not None:
        q = q.where(StripeCredential.id != except_id)
    if (name := await session.scalar(q)) is not None:
        raise DuplicateAccount(f"You've already added {name}. Use \"Replace key\" on it to change its key.")


async def _apply_key(cred: StripeCredential, raw: str, p: Probe, key_type: str, livemode: bool) -> None:
    sealed = await get_cipher().encrypt(raw, cred.aad)
    cred.ciphertext, cred.wrapped_dek, cred.cipher = sealed.ciphertext, sealed.wrapped_dek, sealed.cipher
    cred.key_type, cred.livemode, cred.key_last4 = key_type, livemode, raw[-4:]
    cred.stripe_account_id = p.stripe_account_id
    cred.display_name, cred.settlement_currency = p.display_name, p.settlement_currency
    cred.status, cred.missing_permissions = _status(p), p.missing_permissions
    cred.last_verified_at = datetime.now(UTC)


async def _commit(session: AsyncSession, user: CurrentUser) -> None:
    try:
        await session.commit()
    except IntegrityError:  # the unique (user, account) constraint, if two adds race
        await session.rollback()
        raise DuplicateAccount("You've already added this Stripe account.") from None
    clear_scope_cache(user.id)


async def add(session: AsyncSession, user: CurrentUser, raw: str, label: str | None = None) -> StripeCredential:
    raw = raw.strip()
    key_type, livemode = check_format(raw)
    count = await session.scalar(select(func.count()).where(StripeCredential.user_id == user.id))
    if (count or 0) >= MAX_KEYS_PER_USER:
        raise CredentialError(f"You can add up to {MAX_KEYS_PER_USER} accounts.")
    p = await probe(raw)
    await _check_not_duplicate(session, user, p.stripe_account_id)

    cred = StripeCredential(id=uuid.uuid4(), user_id=user.id, label=label or None)
    await _apply_key(cred, raw, p, key_type, livemode)
    session.add(cred)
    await _commit(session, user)
    return cred


async def replace_key(session: AsyncSession, user: CurrentUser, credential_id: uuid.UUID, raw: str) -> StripeCredential:
    """Rotate a stored key. The new key must be for the same Stripe account."""
    cred = await get_for_user(session, user, credential_id)
    raw = raw.strip()
    key_type, livemode = check_format(raw)
    p = await probe(raw)
    if cred.stripe_account_id and p.stripe_account_id and p.stripe_account_id != cred.stripe_account_id:
        raise CredentialError(f"This key is for a different Stripe account ({p.display_name}). Add it as a new account instead.")
    await _check_not_duplicate(session, user, p.stripe_account_id, except_id=cred.id)

    await _apply_key(cred, raw, p, key_type, livemode)
    await _commit(session, user)
    fetch.clear_credential(cred.id)
    return cred


async def reverify(session: AsyncSession, user: CurrentUser, credential_id: uuid.UUID) -> StripeCredential:
    """Check a stored key again, e.g. after granting it more permissions in Stripe."""
    cred = await get_for_user(session, user, credential_id)
    raw = await get_cipher().decrypt(cred.sealed, credential_aad(user.id, cred.id))
    try:
        p = await probe(raw)
    except InvalidKey:
        cred.status, cred.missing_permissions = "invalid", []
    else:
        cred.status, cred.missing_permissions = _status(p), p.missing_permissions
        cred.display_name, cred.settlement_currency = p.display_name, p.settlement_currency
        cred.stripe_account_id = cred.stripe_account_id or p.stripe_account_id
    cred.last_verified_at = datetime.now(UTC)
    await _commit(session, user)
    fetch.clear_credential(cred.id)
    return cred


async def rename(session: AsyncSession, user: CurrentUser, credential_id: uuid.UUID, label: str | None) -> StripeCredential:
    cred = await get_for_user(session, user, credential_id)
    cred.label = label or None
    await _commit(session, user)
    return cred


async def delete(session: AsyncSession, user: CurrentUser, credential_id: uuid.UUID) -> None:
    cred = await get_for_user(session, user, credential_id)
    await session.delete(cred)
    await _commit(session, user)
    fetch.clear_credential(credential_id)
