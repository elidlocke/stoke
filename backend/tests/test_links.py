"""The writer's revenue sources and social profiles, through the API."""

import httpx
import pytest
import respx
from sqlalchemy import delete, select

from app.auth import current_user
from app.db_models import User, WriterLink
from app.links import MAX_LINKS
from app.main import app
from tests.conftest import add_key, mock_stripe_keys, stripe_account as account

KEY_A = "rk_test_" + "a" * 24 + "A1b2"

CALENDLY = {
    "category": "revenue_source", "kind": "calendly", "name": "1:1 strategy call",
    "url": "https://calendly.com/me/strategy", "paid_via_account_id": "acct_a",
}


@pytest.fixture
def stripe():
    with respx.mock(assert_all_called=False) as mock:
        mock_stripe_keys(mock, {KEY_A: account("acct_a", "Creator A")})
        yield mock


@pytest.fixture
def as_user():
    def sign_in(user):
        app.dependency_overrides[current_user] = lambda: user
    yield sign_in
    app.dependency_overrides.clear()


@pytest.fixture
async def api():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        yield client


async def test_add_list_update_delete(db, make_user, stripe, as_user, api):
    user = await make_user()
    as_user(user)
    async with db() as session:
        await add_key(session, user, KEY_A)

    resp = await api.post("/api/links", json=CALENDLY)
    assert resp.status_code == 201, resp.text
    source = resp.json()
    assert source["purchase"] == "repeat"  # Calendly's default
    assert source["paid_via_account_id"] == "acct_a"

    gumroad = {"category": "revenue_source", "kind": "gumroad", "name": "Pitch templates", "url": "https://me.gumroad.com/l/pitch"}
    assert (await api.post("/api/links", json=gumroad)).json()["purchase"] == "once"
    social = {"category": "social", "kind": "instagram", "url": "https://instagram.com/me"}
    assert (await api.post("/api/links", json=social)).json()["name"] is None

    listed = (await api.get("/api/links")).json()["links"]
    assert [link["kind"] for link in listed] == ["calendly", "gumroad", "instagram"]  # in the order added

    changed = {**CALENDLY, "name": "Strategy call", "purchase": "once", "paid_via_account_id": None}
    resp = await api.put(f"/api/links/{source['id']}", json=changed)
    assert resp.status_code == 200, resp.text
    assert (resp.json()["name"], resp.json()["purchase"], resp.json()["paid_via_account_id"]) == ("Strategy call", "once", None)

    assert (await api.delete(f"/api/links/{source['id']}")).status_code == 204
    assert [link["kind"] for link in (await api.get("/api/links")).json()["links"]] == ["gumroad", "instagram"]


@pytest.mark.parametrize("body", [
    {**CALENDLY, "kind": "instagram"},  # a social type in the revenue sources list
    {**CALENDLY, "kind": "coaching"},  # not a supported platform
    {**CALENDLY, "name": None},  # revenue sources need a name
    {**CALENDLY, "url": "http://calendly.com/me"},
    {**CALENDLY, "url": "calendly"},
    {**CALENDLY, "purchase": "sometimes"},
    {"category": "social", "kind": "x", "url": "https://x.com/me", "purchase": "once"},  # only revenue sources are paid for
    {"category": "program", "kind": "substack_referral", "url": "https://me.substack.com/leaderboard"},  # not yet
    {"category": "newsletter", "kind": "other", "url": "https://example.com"},
])
async def test_invalid_links_are_rejected(db, make_user, stripe, as_user, api, body):
    user = await make_user()
    as_user(user)
    async with db() as session:
        await add_key(session, user, KEY_A)
    assert (await api.post("/api/links", json=body)).status_code == 422


async def test_paid_through_must_be_the_users_own_account(db, make_user, stripe, as_user, api):
    as_user(await make_user())
    resp = await api.post("/api/links", json=CALENDLY)  # acct_a hasn't been added
    assert resp.status_code == 400 and "isn't one you've added" in resp.json()["detail"]


async def test_a_link_cant_change_list(db, make_user, as_user, api):
    as_user(await make_user())
    link = (await api.post("/api/links", json={"category": "social", "kind": "x", "url": "https://x.com/me"})).json()
    resp = await api.put(f"/api/links/{link['id']}", json={**CALENDLY, "kind": "other"})
    assert resp.status_code == 400


async def test_other_users_links_are_not_found(db, make_user, as_user, api):
    as_user(await make_user())
    body = {"category": "social", "kind": "x", "url": "https://x.com/me"}
    link_id = (await api.post("/api/links", json=body)).json()["id"]

    as_user(await make_user())
    assert (await api.get("/api/links")).json() == {"links": []}
    assert (await api.put(f"/api/links/{link_id}", json={**body, "url": "https://x.com/them"})).status_code == 404
    assert (await api.delete(f"/api/links/{link_id}")).status_code == 404

    async with db() as session:
        assert await session.scalar(select(WriterLink.url)) == "https://x.com/me"  # untouched


async def test_link_cap(db, make_user, as_user, api):
    as_user(await make_user())
    body = {"category": "social", "kind": "website", "url": "https://example.com"}
    for _ in range(MAX_LINKS):
        assert (await api.post("/api/links", json=body)).status_code == 201
    assert (await api.post("/api/links", json=body)).status_code == 400


async def test_links_are_deleted_with_the_user(db, make_user, as_user, api):
    user = await make_user()
    as_user(user)
    await api.post("/api/links", json={"category": "social", "kind": "x", "url": "https://x.com/me"})
    async with db() as session:
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()
        assert await session.scalar(select(WriterLink.id)) is None
