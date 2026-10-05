"""Which Stripe accounts are in scope, and the credentials used to read each one.

Two ways to reach an account, usable together:
- "platform"/"connected": our own Connect platform key; connected accounts via the Stripe-Account header.
- "own_key": a key the creator issued from their own Stripe account (e.g. a Substack author's
  Standard account). This is the realistic production path, since creators don't own the platform.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Literal

import stripe
from cachetools import TTLCache

from app.config import get_settings

log = logging.getLogger(__name__)

Access = Literal["platform", "connected", "own_key"]


class NoCredentials(Exception):
    pass


class MissingPermission(Exception):
    """A restricted key lacks read access to a resource a view needs."""

    def __init__(self, resource: str):
        super().__init__(f"A Stripe key can't read {resource}. Grant it \"{resource}: Read\" and restart the API.")


@dataclass(frozen=True)
class Account:
    id: str
    display_name: str
    settlement_currency: str
    access: Access
    client: stripe.StripeClient = field(compare=False, repr=False)

    @property
    def options(self) -> dict:
        """Per-request options: connected accounts are addressed via the Stripe-Account header."""
        return {"stripe_account": self.id} if self.access == "connected" else {}


@dataclass(frozen=True)
class AccountScope:
    accounts: list[Account]  # accounts whose charges are aggregated
    reporting_currency: str


def make_client(api_key: str) -> stripe.StripeClient:
    return stripe.StripeClient(api_key, max_network_retries=3, http_client=stripe.HTTPXClient())


def _to_account(obj: dict, access: Access, client: stripe.StripeClient) -> Account:
    name = (
        ((obj.get("settings") or {}).get("dashboard") or {}).get("display_name")
        or (obj.get("business_profile") or {}).get("name")
        or obj["id"]
    )
    return Account(
        id=obj["id"],
        display_name=name,
        settlement_currency=(obj.get("default_currency") or "usd").lower(),
        access=access,
        client=client,
    )


async def _platform_accounts(api_key: str) -> tuple[Account, list[Account]]:
    settings = get_settings()
    client = make_client(api_key)
    platform = _to_account((await client.v1.accounts.retrieve_current_async()).to_dict(), "platform", client)

    if settings.account_allowlist:
        objs = await asyncio.gather(
            *(client.v1.accounts.retrieve_async(a) for a in settings.account_allowlist)
        )
    else:
        page = await client.v1.accounts.list_async({"limit": 100})
        objs = [a async for a in page.auto_paging_iter()]
    return platform, [_to_account(o.to_dict(), "connected", client) for o in objs]


async def _own_key_account(api_key: str, index: int) -> Account:
    client = make_client(api_key)
    try:
        obj = (await client.v1.accounts.retrieve_current_async()).to_dict()
    except stripe.PermissionError:
        # Reading /v1/account needs the key's "Accounts: Read" permission. Without it, use a
        # placeholder name and take the payout currency from the account's own balance history.
        log.warning("Key #%d can't read its account details (grant Accounts: Read); using a placeholder", index)
        latest = (await client.v1.balance_transactions.list_async({"limit": 1})).data
        obj = {"id": f"key-{index}", "business_profile": {"name": f"Account {index}"},
               "default_currency": latest[0].currency if latest else get_settings().reporting_currency}
    return _to_account(obj, "own_key", client)


_scope_cache: TTLCache[str, AccountScope] = TTLCache(maxsize=1, ttl=300)


def clear_scope_cache() -> None:
    _scope_cache.clear()


async def get_scope(refresh: bool = False) -> AccountScope:
    if not refresh and (cached := _scope_cache.get("scope")):
        return cached

    settings = get_settings()
    if settings.stripe_platform_key is None and not settings.account_keys:
        raise NoCredentials("Set STRIPE_PLATFORM_KEY and/or STRIPE_ACCOUNT_KEYS in .env")

    platform: Account | None = None
    accounts: list[Account] = []
    if settings.stripe_platform_key is not None:
        platform, connected = await _platform_accounts(settings.stripe_platform_key.get_secret_value())
        accounts = ([platform] if settings.include_platform else []) + connected

    own = await asyncio.gather(
        *(_own_key_account(k, i) for i, k in enumerate(settings.account_keys, start=1))
    )
    # An account reachable both ways is read once, preferring its own key.
    own_ids = {a.id for a in own}
    accounts = [a for a in accounts if a.id not in own_ids] + list(own)

    reporting = (
        settings.reporting_currency
        or (platform.settlement_currency if platform else None)
        or (accounts[0].settlement_currency if accounts else "usd")
    ).lower()

    scope = AccountScope(accounts=accounts, reporting_currency=reporting)
    _scope_cache["scope"] = scope
    return scope
