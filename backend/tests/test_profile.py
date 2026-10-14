"""The writer's profile: plan labels and where payments come from."""

import httpx
import pytest

from app import fetch, profile, service
from app.actions import NEWSLETTER, Labels, RevenueSource
from app.aggregate import Fee
from app.auth import current_user
from app.customer_id import ref_id
from app.main import app
from app.stripe_client import Account, AccountScope
from tests.test_actions import pay, sub

SUBSTACK_FEE = (Fee("application_fee", "Substack application fee", 100),)
MAVEN_FEE = (Fee("application_fee", "Maven Platform Fee", 500),)


def test_plans_suggest_a_label_from_the_name_price_and_interval():
    subs = [
        sub("a@x.com", 100, interval="year", price_id="p_year", price_amount=8000, price_currency="usd", plan="Yearly plan"),
        sub("b@x.com", 100, interval="year", price_id="p_year", price_amount=8000, price_currency="usd", plan="Yearly plan"),
        sub("c@x.com", 100, interval="year", price_id="p_top", price_amount=25000, price_currency="usd", plan="Yearly plan"),
        sub("m@x.com", 100, price_id="p_month", price_amount=800, price_currency="usd"),
        sub("q@x.com", 100, interval="quarter", price_id="p_quarter", price_amount=2000, price_currency="usd", plan="Plan"),
        sub("old@x.com", 100),  # stored before prices: not listed
    ]
    plans = profile.plans(subs, Labels(plans={"p_year": "standard", "p_quarter": "group"}))
    assert [(p.price_id, p.subscribers, p.label, p.suggested) for p in plans] == [
        ("p_year", 2, "annual", "annual"),  # the legacy "standard": not Founding, billed yearly
        ("p_month", 1, None, "monthly"), ("p_quarter", 1, "group", "other"), ("p_top", 1, None, "founding"),
    ]


def test_payment_sources_name_their_platform_and_suggest_a_label():
    course = RevenueSource("course", "maven", "Course", "once", None)
    payments = [
        pay("a@x.com", 10, application="ca_sub", settled_fees=SUBSTACK_FEE),
        pay("b@x.com", 5, application="ca_sub", settled_fees=SUBSTACK_FEE),
        pay("a@x.com", 20, "manual", application="ca_maven", settled_fees=MAVEN_FEE, description="Course seat"),
        pay("c@x.com", 3, "manual"),  # made directly: not a source
    ]
    found = profile.payment_sources(payments, [course], Labels(applications={"ca_maven": "deleted-link"}))
    assert [(s.application, s.platform, s.payments, s.customers, s.suggested, s.label) for s in found] == [
        ("ca_sub", "Substack", 2, 2, NEWSLETTER, None),
        ("ca_maven", "Maven", 1, 1, "course", None),  # its label pointed at a deleted revenue source
    ]
    assert found[1].example == "Course seat"


# ---- Through the API ----


ACCOUNT = Account("acct_a", "Creator", "usd", "own_key", client=None)


@pytest.fixture
def stripe_data(monkeypatch):
    async def scope(user, refresh=False):
        return AccountScope(accounts=[ACCOUNT], reporting_currency="usd")

    async def payments_since(account, since, refresh=False):
        return [pay("a@x.com", 20, "manual", application="ca_maven", settled_fees=MAVEN_FEE)]

    async def subscriptions(account, refresh=False):
        return [sub("a@x.com", 100, interval="year", price_id="p_year", price_amount=8000, price_currency="usd")]

    monkeypatch.setattr(service, "get_scope", scope)
    monkeypatch.setattr(fetch, "payments_since", payments_since)
    monkeypatch.setattr(fetch, "subscriptions", subscriptions)


@pytest.fixture
async def api():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


async def test_label_plans_and_payment_sources(db, make_user, stripe_data, api):
    user = await make_user()
    app.dependency_overrides[current_user] = lambda: user

    [plan] = (await api.get("/api/plans")).json()["plans"]
    assert plan["id"] == ref_id("price", "p_year") and "p_year" not in str(plan)
    assert (plan["label"], plan["suggested"]) == (None, "annual")
    assert (await api.put(f"/api/plans/{plan['id']}", json={"label": "founding"})).status_code == 204
    assert (await api.get("/api/plans")).json()["plans"][0]["label"] == "founding"
    assert (await api.put(f"/api/plans/{plan['id']}", json={"label": "standard"})).status_code == 422
    assert (await api.put(f"/api/plans/{plan['id']}", json={"label": None})).status_code == 204
    assert (await api.get("/api/plans")).json()["plans"][0]["label"] is None
    assert (await api.put(f"/api/plans/{'0' * 24}", json={"label": "founding"})).status_code == 404

    course = {"category": "revenue_source", "kind": "maven", "name": "Course", "url": "https://maven.com/me/course"}
    link_id = (await api.post("/api/links", json=course)).json()["id"]
    [source] = (await api.get("/api/payment-sources")).json()["sources"]
    assert "ca_maven" not in str(source)
    assert (source["platform"], source["suggested"], source["label"]) == ("Maven", link_id, None)
    resp = await api.put(f"/api/payment-sources/{source['id']}", json={"label": link_id})
    assert resp.status_code == 204
    assert (await api.get("/api/payment-sources")).json()["sources"][0]["label"] == link_id
    resp = await api.put(f"/api/payment-sources/{source['id']}", json={"label": "not-a-link"})
    assert resp.status_code == 400

    # The actions read the saved labels.
    async with db() as session:
        assert await profile.labels(session, user) == Labels(plans={}, applications={"ca_maven": link_id})
    assert (await api.get("/api/actions")).status_code == 200

    # Another writer sees none of it.
    other = await make_user()
    app.dependency_overrides[current_user] = lambda: other
    assert (await api.get("/api/plans")).json()["plans"][0]["label"] is None
    assert (await api.get("/api/payment-sources")).json()["sources"][0]["label"] is None
