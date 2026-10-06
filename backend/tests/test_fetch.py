"""Exercise the real Stripe SDK async paths against a mocked HTTP layer."""

from urllib.parse import parse_qs

import httpx
import respx

import pytest

from app import fetch
from app.stripe_client import Account, MissingPermission, make_client
from tests.conftest import make_canceled_subscription, make_failed_pi, make_invoice, make_pi, make_subscription

CONNECTED = Account("acct_conn", "Creator", "usd", "connected", make_client("sk_test_platform"))
PLATFORM = Account("acct_platform", "Platform", "usd", "platform", make_client("sk_test_platform"))
OWN = Account("acct_own", "Own", "usd", "own_key", make_client("rk_test_creator"))

PI_URL = "https://api.stripe.com/v1/payment_intents"
INVOICE_URL = "https://api.stripe.com/v1/invoices"
SUBSCRIPTION_URL = "https://api.stripe.com/v1/subscriptions"


def page(data, url, has_more=False):
    return {"object": "list", "url": url, "has_more": has_more, "data": data}


def query(call) -> dict:
    return parse_qs(call.request.url.query.decode())


@respx.mock
async def test_payments_joined_to_invoices_with_pagination_header_and_expand():
    pis = respx.get(PI_URL).mock(side_effect=[
        httpx.Response(200, json=page([make_pi(id="pi_1")], "/v1/payment_intents", has_more=True)),
        httpx.Response(200, json=page([
            make_failed_pi(id="pi_2"),
            make_pi(id="pi_never", status="requires_payment_method", latest_charge=None),
        ], "/v1/payment_intents")),
    ])
    invoices = respx.get(INVOICE_URL).mock(return_value=httpx.Response(200, json=page(
        [make_invoice("pi_2", billing_reason="manual", attempt_count=4)], "/v1/invoices"
    )))

    payments = await fetch.payments_since(CONNECTED, since=100 * 86400)

    assert [(p.id, p.status, p.attempts, p.billing_reason) for p in payments] == [
        ("pi_1", "succeeded", 1, None),  # no invoice: a one-off payment
        ("pi_2", "failed", 4, "manual"),  # joined to its invoice; never-attempted pi skipped
    ]
    first, second = pis.calls
    assert first.request.headers["Stripe-Account"] == "acct_conn"
    q = query(first)
    assert q["created[gte]"] == [str(100 * 86400)]
    assert [q[f"expand[{i}]"][0] for i in range(len(fetch.PI_EXPAND))] == fetch.PI_EXPAND
    assert query(second)["starting_after"] == ["pi_1"]
    # Invoices are fetched from further back so dunning retries still find their invoice.
    assert query(invoices.calls[0])["created[gte]"] == [str(100 * 86400 - fetch.INVOICE_LOOKBACK)]
    assert query(invoices.calls[0])["expand[0]"] == ["data.payments"]

    # Narrower window served from cache: no new requests.
    await fetch.payments_since(CONNECTED, since=2_000_000_000)
    assert pis.call_count == 2 and invoices.call_count == 1


@respx.mock
async def test_platform_requests_have_no_account_header():
    route = respx.get(PI_URL).mock(return_value=httpx.Response(200, json=page([], "/v1/payment_intents")))
    respx.get(INVOICE_URL).mock(return_value=httpx.Response(200, json=page([], "/v1/invoices")))
    await fetch.payments_since(PLATFORM, since=None)
    assert "Stripe-Account" not in route.calls[0].request.headers
    assert "created[gte]" not in query(route.calls[0])


@respx.mock
async def test_own_key_account_uses_its_own_key_without_account_header():
    route = respx.get(PI_URL).mock(return_value=httpx.Response(200, json=page([], "/v1/payment_intents")))
    respx.get(INVOICE_URL).mock(return_value=httpx.Response(200, json=page([], "/v1/invoices")))
    await fetch.payments_since(OWN, since=None)
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Bearer rk_test_creator"
    assert "Stripe-Account" not in req.headers


@respx.mock
async def test_subscriptions_include_canceled_and_are_cached():
    route = respx.get(SUBSCRIPTION_URL).mock(return_value=httpx.Response(200, json=page(
        [make_subscription(), make_canceled_subscription(id="sub_2")], "/v1/subscriptions"
    )))

    subs = await fetch.subscriptions(CONNECTED)

    assert [(s.id, s.status) for s in subs] == [("sub_1", "active"), ("sub_2", "canceled")]
    req = route.calls[0].request
    assert req.headers["Stripe-Account"] == "acct_conn"
    q = query(route.calls[0])
    assert q["status"] == ["all"]  # Stripe omits canceled subscriptions by default
    assert [q[f"expand[{i}]"][0] for i in range(2)] == fetch.SUBSCRIPTION_EXPAND

    await fetch.subscriptions(CONNECTED)
    assert route.call_count == 1
    await fetch.subscriptions(CONNECTED, refresh=True)
    assert route.call_count == 2


@respx.mock
async def test_subscriptions_without_read_permission():
    respx.get(SUBSCRIPTION_URL).mock(return_value=httpx.Response(403, json={
        "error": {"type": "invalid_request_error", "message": "restricted key lacks rak_subscription_read"}
    }))
    with pytest.raises(MissingPermission, match="Subscriptions: Read"):
        await fetch.subscriptions(OWN)
