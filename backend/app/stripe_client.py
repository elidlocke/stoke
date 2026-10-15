"""Which Stripe accounts are in a user's scope, and the credentials used to read each one.

Two ways to reach an account, usable together:
- "own_key": the creator's own Stripe account (e.g. a Substack author's Standard account), read with
  Stoke's Stripe App installed on it (app/stripe_app.py), or a key they issued before the app existed.
  Stored encrypted per user (see app/credentials.py). The production path, since creators don't own
  the platform.
- "platform"/"connected": a Connect platform key from .env; connected accounts via the
  Stripe-Account header. Local development and simulation only (DEV_MODE).
"""

import asyncio
from dataclasses import dataclass, field
from typing import Literal

import stripe
from cachetools import TTLCache
from sqlalchemy import select

from app import stripe_app
from app.auth import CurrentUser
from app.config import get_settings
from app.crypto import get_cipher
from app.db import sessionmaker
from app.db_models import StripeCredential, UserSettings, credential_account_id

Access = Literal["platform", "connected", "own_key"]

# Every request, and so every stored object, uses this API version rather than whatever the SDK or
# the account defaults to. Changing it changes the shape of stored data: run scripts/resync.py after.
# Kept equal to the installed SDK's version (tests/test_sync.py checks), so upgrading the SDK is a
# deliberate change too.
STRIPE_API_VERSION = "2026-08-26.dahlia"


class NoCredentials(Exception):
    pass


class MissingPermission(Exception):
    """A restricted key lacks read access to a resource a view needs."""

    def __init__(self, resource: str):
        super().__init__(f"A Stripe key can't read {resource}. Grant it \"{resource}: Read\", then re-verify it in Settings.")


@dataclass(frozen=True)
class Account:
    id: str
    display_name: str
    settlement_currency: str
    access: Access
    client: stripe.StripeClient = field(compare=False, repr=False)
    credential_id: str | None = field(default=None, compare=False)  # the stored key, for "own_key"
    livemode: bool = field(default=False, compare=False)
    # What the key can't read (see app/credentials.py). Stored objects are shared by everyone with a
    # key to the account, so each user is only shown the kinds their own key can read.
    missing_permissions: tuple[str, ...] = field(default=(), compare=False)

    @property
    def cache_key(self) -> str:
        """Key for cached Stripe reads. Reads made with a creator's key are cached per key: two users
        holding keys to the same account may have granted them different permissions."""
        return f"{self.id}:{self.credential_id}" if self.credential_id else self.id

    @property
    def options(self) -> dict:
        """Per-request options: connected accounts are addressed via the Stripe-Account header."""
        return {"stripe_account": self.id} if self.access == "connected" else {}


@dataclass(frozen=True)
class AccountScope:
    accounts: list[Account]  # accounts whose charges are aggregated
    reporting_currency: str


def make_client(api_key: str) -> stripe.StripeClient:
    return stripe.StripeClient(
        api_key, stripe_version=STRIPE_API_VERSION, max_network_retries=3, http_client=stripe.HTTPXClient()
    )


def key_livemode(api_key: str) -> bool:
    return api_key.startswith(("sk_live_", "rk_live_"))


def account_name(obj: dict) -> str:
    return (
        ((obj.get("settings") or {}).get("dashboard") or {}).get("display_name")
        or (obj.get("business_profile") or {}).get("name")
        or obj["id"]
    )


def _to_account(obj: dict, access: Access, client: stripe.StripeClient, livemode: bool) -> Account:
    return Account(
        id=obj["id"],
        display_name=account_name(obj),
        settlement_currency=(obj.get("default_currency") or "usd").lower(),
        access=access,
        client=client,
        livemode=livemode,
    )


async def _platform_accounts(api_key: str) -> tuple[Account, list[Account]]:
    settings = get_settings()
    client = make_client(api_key)
    livemode = key_livemode(api_key)
    platform = _to_account((await client.v1.accounts.retrieve_current_async()).to_dict(), "platform", client, livemode)

    if settings.account_allowlist:
        objs = await asyncio.gather(
            *(client.v1.accounts.retrieve_async(a) for a in settings.account_allowlist)
        )
    else:
        page = await client.v1.accounts.list_async({"limit": 100})
        objs = [a async for a in page.auto_paging_iter()]
    return platform, [_to_account(o.to_dict(), "connected", client, livemode) for o in objs]


_scope_cache: TTLCache[str, AccountScope] = TTLCache(maxsize=1024, ttl=300)


def clear_scope_cache(user_id: object | None = None) -> None:
    """Forget one user's scope (after their keys or settings change), or everyone's."""
    if user_id is None:
        _scope_cache.clear()
    else:
        _scope_cache.pop(str(user_id), None)


async def _secret(c: StripeCredential) -> str | None:
    """The API key to read a credential's account with: the Stripe App's current access token, or the stored
    key. None if the app was uninstalled (the credential is then marked invalid)."""
    if c.is_app:
        try:
            return await stripe_app.access_token(c)
        except stripe_app.AppDisconnected:
            return None
    return await get_cipher().decrypt(c.sealed, c.aad)


async def own_key_accounts(creds: list[StripeCredential]) -> list[Account]:
    keys = await asyncio.gather(*(_secret(c) for c in creds))
    return [
        Account(
            id=credential_account_id(c),
            display_name=c.label or c.display_name,
            settlement_currency=c.settlement_currency,
            access="own_key",
            client=make_client(key),
            credential_id=str(c.id),
            livemode=c.livemode,
            missing_permissions=tuple(c.missing_permissions),
        )
        for c, key in zip(creds, keys)
        if key is not None
    ]


async def get_scope(user: CurrentUser, refresh: bool = False) -> AccountScope:
    if not refresh and (cached := _scope_cache.get(str(user.id))):
        return cached

    async with sessionmaker()() as session:
        # A key Stripe rejected (revoked or rolled) is left out until it's replaced.
        creds = list(await session.scalars(
            select(StripeCredential)
            .where(StripeCredential.user_id == user.id, StripeCredential.status != "invalid")
            .order_by(StripeCredential.created_at)
        ))
        prefs = await session.get(UserSettings, user.id)

    platform_key = get_settings().dev_platform_key
    if not creds and platform_key is None:
        raise NoCredentials("Connect Stripe in Settings to see your customers.")

    platform: Account | None = None
    accounts: list[Account] = []
    if platform_key is not None:
        platform, connected = await _platform_accounts(platform_key)
        accounts = ([platform] if get_settings().include_platform else []) + connected

    own = await own_key_accounts(creds)
    if not own and platform_key is None:  # each one's Stripe App was uninstalled
        raise NoCredentials("Connect Stripe in Settings to see your customers.")
    # An account reachable both ways is read once, preferring its own key.
    own_ids = {a.id for a in own}
    accounts = [a for a in accounts if a.id not in own_ids] + own

    reporting = (
        (prefs.reporting_currency if prefs else None)
        or (platform.settlement_currency if platform else None)
        or (accounts[0].settlement_currency if accounts else "usd")
    ).lower()

    scope = AccountScope(accounts=accounts, reporting_currency=reporting)
    _scope_cache[str(user.id)] = scope
    return scope
