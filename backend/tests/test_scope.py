"""Account discovery across a platform key and per-creator keys."""

import httpx
import pytest
import respx

from app.stripe_client import NoCredentials, get_scope


def account(id, name, currency="usd"):
    return {"id": id, "object": "account", "business_profile": {"name": name}, "default_currency": currency}


def by_key(mapping):
    def handler(request):
        return httpx.Response(200, json=mapping[request.headers["Authorization"].removeprefix("Bearer ")])
    return handler


@respx.mock
async def test_platform_and_own_keys_combined(monkeypatch):
    monkeypatch.setenv("STRIPE_PLATFORM_KEY", "sk_test_platform")
    monkeypatch.setenv("STRIPE_ACCOUNT_KEYS", "rk_test_a, rk_test_b")
    respx.get("https://api.stripe.com/v1/account").mock(side_effect=by_key({
        "sk_test_platform": account("acct_platform", "Platform", "gbp"),
        "rk_test_a": account("acct_a", "Creator A", "eur"),
        "rk_test_b": account("acct_conn", "Also connected"),
    }))
    respx.get("https://api.stripe.com/v1/accounts").mock(return_value=httpx.Response(200, json={
        "object": "list", "url": "/v1/accounts", "has_more": False,
        "data": [account("acct_conn", "Connected"), account("acct_other", "Other")],
    }))

    scope = await get_scope()

    assert [(a.id, a.access) for a in scope.accounts] == [
        ("acct_platform", "platform"),
        ("acct_other", "connected"),
        ("acct_a", "own_key"),
        ("acct_conn", "own_key"),  # reachable both ways: read with its own key, once
    ]
    assert scope.reporting_currency == "gbp"  # platform's payout currency


@respx.mock
async def test_own_keys_only(monkeypatch):
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.setenv("STRIPE_ACCOUNT_KEYS", "rk_test_a")
    respx.get("https://api.stripe.com/v1/account").mock(return_value=httpx.Response(200, json=account("acct_a", "A", "eur")))

    scope = await get_scope()

    assert [(a.id, a.access) for a in scope.accounts] == [("acct_a", "own_key")]
    assert scope.reporting_currency == "eur"


@respx.mock
async def test_own_key_without_account_read_permission(monkeypatch):
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.setenv("STRIPE_ACCOUNT_KEYS", "rk_test_a")
    respx.get("https://api.stripe.com/v1/account").mock(return_value=httpx.Response(
        403, json={"error": {"type": "invalid_request_error", "message": "restricted key lacks permission"}}
    ))
    respx.get("https://api.stripe.com/v1/balance_transactions").mock(return_value=httpx.Response(200, json={
        "object": "list", "url": "/v1/balance_transactions", "has_more": False,
        "data": [{"id": "txn_1", "object": "balance_transaction", "currency": "cad", "amount": 100}],
    }))

    scope = await get_scope()
    [acct] = scope.accounts
    assert (acct.id, acct.display_name, acct.settlement_currency) == ("key-1", "Account 1", "cad")
    assert scope.reporting_currency == "cad"


async def test_no_credentials(monkeypatch):
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.delenv("STRIPE_ACCOUNT_KEYS", raising=False)
    with pytest.raises(NoCredentials):
        await get_scope()
