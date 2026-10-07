import asyncio
import copy
import os
import uuid

import dotenv

# Keep the developer's real .env (and its keys) out of tests.
dotenv.load_dotenv = lambda *args, **kwargs: False
os.environ["CUSTOMER_ID_SECRET"] = "22" * 32
os.environ["STOKE_ENCRYPTION_KEY"] = "11" * 32
os.environ["AUTH0_DOMAIN"] = "stoke-test.auth0.local"
os.environ["AUTH0_AUDIENCE"] = "https://api.stoke.test"
os.environ["ALLOWED_HOSTS"] = "testserver"
os.environ.pop("DEV_MODE", None)
# A Postgres server for the tests that need one (docker compose up -d); they use their own database.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://stoke:stoke@127.0.0.1:5432/stoke_test"
)

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app import db as app_db  # noqa: E402
from app import fetch  # noqa: E402
from app.auth import CurrentUser, clear_jwks_cache  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.crypto import get_cipher  # noqa: E402
from app.db_models import User  # noqa: E402
from app.stripe_client import clear_scope_cache  # noqa: E402

SENSITIVE_CUSTOMER = {
    "id": "cus_1",
    "object": "customer",
    "email": "Ada@Example.com",
    "phone": "+15555550100",
    "address": {"line1": "1 SENSITIVE St"},
    "metadata": {"crm_id": "SENSITIVE_METADATA"},
}


def make_charge(**overrides) -> dict:
    """A successful charge with balance_transaction and refunds expanded.

    Deliberately includes sensitive fields so tests can assert they never reach API responses.
    """
    charge = {
        "id": "ch_1",
        "object": "charge",
        "amount": 5000,
        "amount_captured": 5000,
        "amount_refunded": 0,
        "currency": "usd",
        "created": 1_750_000_000,
        "status": "succeeded",
        "paid": True,
        "description": "Pro plan",
        "receipt_email": None,
        "receipt_url": "https://pay.stripe.com/receipts/secret-receipt",
        "payment_method": "pm_SENSITIVE",
        "metadata": {"internal_note": "SENSITIVE_METADATA"},
        "billing_details": {
            "email": None,
            "name": "Ada Lovelace",
            "phone": "+15555550100",
            "address": {"line1": "1 SENSITIVE St", "city": "London", "postal_code": "N1"},
        },
        "payment_method_details": {
            "type": "card",
            "card": {"brand": "visa", "last4": "4242", "fingerprint": "FPSENSITIVE", "exp_year": 2030},
        },
        "balance_transaction": {
            "id": "txn_1",
            "object": "balance_transaction",
            "amount": 5000,
            "currency": "usd",
            "exchange_rate": None,
            "fee": 175,
            "net": 4825,
            "fee_details": [
                {"type": "application_fee", "amount": 50, "currency": "usd", "description": "Substack application fee"},
                {"type": "stripe_fee", "amount": 125, "currency": "usd", "description": "Stripe processing fees"},
            ],
        },
        "refunds": {"object": "list", "data": []},
    }
    charge.update(overrides)
    return charge


def make_pi(**overrides) -> dict:
    """A succeeded PaymentIntent shaped like Stripe's API with customer + latest_charge expanded."""
    pi = {
        "id": "pi_1",
        "object": "payment_intent",
        "amount": 5000,
        "currency": "usd",
        "created": 1_750_000_000,
        "status": "succeeded",
        "description": "Pro plan",
        "receipt_email": None,
        "client_secret": "pi_1_secret_SENSITIVE",
        "payment_method": "pm_SENSITIVE",
        "metadata": {"internal_note": "SENSITIVE_METADATA"},
        "customer": copy.deepcopy(SENSITIVE_CUSTOMER),
        "latest_charge": make_charge(),
        "last_payment_error": None,
    }
    pi.update(overrides)
    return pi


def make_dispute(status="lost", returned=False, **overrides) -> dict:
    """A dispute as expanded on a charge, with the sensitive evidence a real one carries."""
    bts = [] if status.startswith("warning") else [{
        "id": "txn_d1", "object": "balance_transaction", "amount": -5000, "fee": 1500, "currency": "usd",
        "created": 1_760_000_000, "fee_details": [{"type": "stripe_fee", "amount": 1500, "description": "Dispute fee"}],
    }]
    if returned:
        bts.append({"id": "txn_d2", "object": "balance_transaction", "amount": 5000, "fee": 0, "currency": "usd",
                    "created": 1_761_000_000, "fee_details": []})
    dispute = {
        "id": "dp_1", "object": "dispute", "amount": 5000, "currency": "usd", "created": 1_760_000_000,
        "status": status, "reason": "fraudulent", "charge": "ch_1", "payment_intent": "pi_1",
        "evidence": {
            "customer_name": "Ada Lovelace", "customer_email_address": "ada@example.com",
            "billing_address": "1 SENSITIVE St", "uncategorized_text": "SENSITIVE evidence",
        },
        "evidence_details": {"due_by": 1_761_500_000, "has_evidence": False},
        "payment_method_details": {"card": {"brand": "visa", "network_reason_code": "10.4"}},
        "metadata": {"internal_note": "SENSITIVE_METADATA"},
        "balance_transactions": bts,
    }
    dispute.update(overrides)
    return dispute


def make_failed_pi(**overrides) -> dict:
    return make_pi(**{
        "status": "requires_payment_method",
        "latest_charge": make_charge(
            status="failed", paid=False, amount_captured=0, balance_transaction=None,
            failure_code="card_declined",
        ),
        "last_payment_error": {
            "code": "card_declined",
            "message": "Your card was declined.",
            "payment_method": {"id": "pm_SENSITIVE", "card": {"last4": "4242"}},
        },
    } | overrides)


def make_invoice(pi_id: str, **overrides) -> dict:
    invoice = {
        "id": "in_1",
        "object": "invoice",
        "billing_reason": "subscription_create",
        "attempt_count": 1,
        "customer_email": "ada@example.com",
        "customer_address": {"line1": "1 SENSITIVE St"},
        "hosted_invoice_url": "https://invoice.stripe.com/SENSITIVE",
        "lines": {"data": [{"description": "1 × Monthly (at $8.00 / month)"}]},
        "payments": {"data": [{"payment": {"type": "payment_intent", "payment_intent": pi_id}}]},
    }
    invoice.update(overrides)
    return invoice


def make_subscription(**overrides) -> dict:
    """An active subscription with customer + latest_invoice expanded, including sensitive fields."""
    sub = {
        "id": "sub_1",
        "object": "subscription",
        "status": "active",
        "created": 1_750_000_000,
        "start_date": 1_750_000_000,
        "canceled_at": None,
        "cancel_at": None,
        "cancel_at_period_end": False,
        "ended_at": None,
        "cancellation_details": {"reason": None, "feedback": None, "comment": None},
        "customer": copy.deepcopy(SENSITIVE_CUSTOMER),
        "default_payment_method": "pm_SENSITIVE",
        "metadata": {"internal_note": "SENSITIVE_METADATA"},
        "items": {"data": [{"id": "si_1", "price": {"id": "price_1", "nickname": None}}]},
        "latest_invoice": make_invoice("pi_1"),
    }
    sub.update(overrides)
    return sub


def make_canceled_subscription(**overrides) -> dict:
    return make_subscription(**{
        "status": "canceled",
        "canceled_at": 1_760_000_000,
        "ended_at": 1_760_000_000,
        "cancellation_details": {
            "reason": "cancellation_requested", "feedback": "too_expensive", "comment": "SENSITIVE comment",
        },
    } | overrides)


def _clear():
    fetch.clear_cache()
    clear_scope_cache()
    get_settings.cache_clear()
    get_cipher.cache_clear()
    clear_jwks_cache()


@pytest.fixture(autouse=True)
def _clear_caches():
    _clear()
    yield
    _clear()


# --- Postgres -------------------------------------------------------------------------------------


async def _create_database(url) -> None:
    conn = await asyncpg.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, database="postgres"
    )
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", url.database):
            await conn.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def _migrated_database():
    url = make_url(TEST_DATABASE_URL)
    try:
        asyncio.run(_create_database(url))
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.fail(f"Tests that use the database need Postgres at {url.host}:{url.port} "
                    f"(run `docker compose up -d`, or set TEST_DATABASE_URL): {exc}")
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


@pytest.fixture
async def db(_migrated_database):
    """The app's database, pointed at the test database and emptied after the test."""
    app_db.configure(TEST_DATABASE_URL, null_pool=True)
    yield app_db.sessionmaker()
    async with app_db.sessionmaker()() as session:
        await session.execute(text("TRUNCATE users, user_settings, stripe_credentials CASCADE"))
        await session.commit()
    await app_db.dispose()


@pytest.fixture
def make_user(db):
    async def make(sub: str | None = None, email: str | None = None) -> CurrentUser:
        user = User(id=uuid.uuid4(), auth_subject=sub or f"auth0|{uuid.uuid4().hex}", email=email)
        async with db() as session:
            session.add(user)
            await session.commit()
        return CurrentUser(id=user.id, auth_subject=user.auth_subject, email=email)
    return make


# --- Stripe keys ----------------------------------------------------------------------------------

RESOURCES = {
    "PaymentIntents": "payment_intents",
    "Invoices": "invoices",
    "Charges": "charges",
    "Customers": "customers",
    "Subscriptions": "subscriptions",
    "Balance transactions": "balance_transactions",
}


def stripe_account(id, name, currency="usd"):
    return {"id": id, "object": "account", "business_profile": {"name": name}, "default_currency": currency}


def _empty_list(path, data=()):
    return {"object": "list", "url": f"/v1/{path}", "has_more": False, "data": list(data)}


def mock_stripe_keys(respx_mock, keys: dict[str, dict | None], *, forbidden: dict[str, set[str]] | None = None,
                     balance_currency: dict[str, str] | None = None) -> None:
    """Answer Stripe like it would for each key: its account (None: the key lacks "Accounts: Read"),
    403 for the resources listed in `forbidden`, and 401 for any key not in `keys`."""
    forbidden = forbidden or {}
    balance_currency = balance_currency or {}

    def key_of(request) -> str:
        return request.headers["Authorization"].removeprefix("Bearer ")

    def unauthorized():
        return httpx.Response(401, json={"error": {"type": "invalid_request_error", "message": "Invalid API Key"}})

    def no_permission():
        return httpx.Response(403, json={"error": {"type": "invalid_request_error", "message": "restricted key"}})

    def account(request):
        key = key_of(request)
        if key not in keys:
            return unauthorized()
        return httpx.Response(200, json=keys[key]) if keys[key] is not None else no_permission()

    respx_mock.get("https://api.stripe.com/v1/account").mock(side_effect=account)

    for name, path in RESOURCES.items():
        def handler(request, name=name, path=path):
            key = key_of(request)
            if key not in keys:
                return unauthorized()
            if name in forbidden.get(key, set()):
                return no_permission()
            data = []
            if path == "balance_transactions" and key in balance_currency:
                data = [{"id": "txn_1", "object": "balance_transaction", "currency": balance_currency[key], "amount": 1}]
            return httpx.Response(200, json=_empty_list(path, data))
        respx_mock.get(f"https://api.stripe.com/v1/{path}").mock(side_effect=handler)
