"""Actions' templates, queues and notes marked sent, through the API."""

import httpx
from sqlalchemy import text
import pytest

from app import fetch, service
from app.auth import current_user
from app.customer_id import customer_id
from app.main import app
from app.stripe_client import Account, AccountScope
from tests.test_actions import pay, sub

ACCOUNT = Account("acct_a", "Creator", "usd", "own_key", client=None)
NEW = "new@x.com"
NEWER = "newer@x.com"


@pytest.fixture
def stripe_data(monkeypatch):
    """Two new paid subscribers: the Welcome action's audience."""
    async def scope(user, refresh=False):
        return AccountScope(accounts=[ACCOUNT], reporting_currency="usd")

    async def payments_since(account, since, refresh=False):
        return [pay(NEW, 5, "subscription_create", take_home=2000, name="JANE DOE"), pay(NEWER, 2, "subscription_create")]

    async def subscriptions(account, refresh=False):
        return [sub(NEW, 5), sub(NEWER, 2)]

    monkeypatch.setattr(service, "get_scope", scope)
    monkeypatch.setattr(fetch, "payments_since", payments_since)
    monkeypatch.setattr(fetch, "subscriptions", subscriptions)


@pytest.fixture
async def api():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def signed_in(db, make_user):
    async def sign_in():
        user = await make_user()
        app.dependency_overrides[current_user] = lambda: user
        return user
    return sign_in


async def _open_welcome(api):
    await api.post("/api/links", json={"category": "social", "kind": "substack", "url": "https://me.substack.com"})
    assert (await api.patch("/api/actions/welcome", json={
        "enabled": True, "subject": "Thanks for {{plan}}", "body": "Hi!\n\nRead more at {{substack}}", "approved": True,
    })).status_code == 204


async def test_template_edits_withdraw_approval(signed_in, stripe_data, api):
    await signed_in()
    body = (await api.get("/api/actions/welcome")).json()
    assert body["template"]["is_default"] and body["template"]["approved_at"] is None
    assert "substack" in {f["name"] for f in body["fields"]}

    await api.patch("/api/actions/welcome", json={"approved": True})
    assert (await api.get("/api/actions/welcome")).json()["template"]["approved_at"] is not None

    await api.patch("/api/actions/welcome", json={"body": "Hi {{plan}}"})
    t = (await api.get("/api/actions/welcome")).json()["template"]
    assert (t["body"], t["is_default"], t["approved_at"]) == ("Hi {{plan}}", False, None)

    resp = await api.patch("/api/actions/welcome", json={"body": "Hi {{last_name}}"})
    assert resp.status_code == 400 and "{{last_name}}" in resp.json()["detail"]
    assert (await api.patch("/api/actions/nope", json={"enabled": True})).status_code == 404


async def test_queue_mark_sent_skip_and_undo(signed_in, stripe_data, api):
    await signed_in()
    assert (await api.get("/api/actions/welcome/queue")).json() == {"open": False, "customers": []}

    await _open_welcome(api)
    welcome = await _library_entry(api, "welcome")
    assert (welcome["open"], welcome["to_send"], welcome["sent"], welcome["last_sent_at"]) == (True, 2, 0, None)
    queue = (await api.get("/api/actions/welcome/queue")).json()
    assert queue["open"]
    assert [c["email"] for c in queue["customers"]] == [NEW, NEWER]  # highest value first
    note = queue["customers"][0]["note"]
    assert note["subject"] == [
        {"text": "Thanks for ", "field": None, "fallback": False}, {"text": "Monthly plan", "field": "plan", "fallback": False},
    ]
    assert {"text": "https://me.substack.com", "field": "substack", "fallback": False} in note["body"]
    assert note["missing"] == []

    resp = await api.post("/api/actions/welcome/outreach", json={
        "customer_id": customer_id(NEW), "status": "sent", "subject": "Thanks!", "body": "Edited before sending",
    })
    assert resp.status_code == 201, resp.text
    sent = resp.json()
    assert (sent["email"], sent["status"], sent["action_title"], sent["body"]) == (NEW, "sent", "Welcome", "Edited before sending")
    assert sent["sent_at"] is not None

    again = await api.post("/api/actions/welcome/outreach", json={"customer_id": customer_id(NEW), "status": "sent"})
    assert again.status_code == 400
    outsider = await api.post("/api/actions/welcome/outreach", json={"customer_id": "0" * 24, "status": "sent"})
    assert outsider.status_code == 400

    skipped = (await api.post("/api/actions/welcome/outreach", json={"customer_id": customer_id(NEWER), "status": "skipped"})).json()
    assert (await api.get("/api/actions/welcome/queue")).json()["customers"] == []

    history = (await api.get("/api/actions/welcome/outreach")).json()["outreach"]
    assert [(o["email"], o["status"]) for o in history] == [(NEWER, "skipped"), (NEW, "sent")]
    contacted = (await api.get("/api/outreach/contacted")).json()["contacted"]
    assert list(contacted) == [customer_id(NEW)]  # skipped isn't contacted
    assert contacted[customer_id(NEW)]["action_kind"] == "welcome"
    [profile_note] = (await api.get(f"/api/customers/{customer_id(NEW)}/outreach")).json()["outreach"]
    assert profile_note["subject"] == "Thanks!"

    welcome = await _library_entry(api, "welcome")
    assert (welcome["enabled"], welcome["sent"], welcome["to_send"]) == (True, 1, 0)
    assert welcome["last_sent_at"] == sent["sent_at"]  # the skip after it isn't a send

    assert (await api.delete(f"/api/outreach/{skipped['id']}")).status_code == 204
    assert [c["email"] for c in (await api.get("/api/actions/welcome/queue")).json()["customers"]] == [NEWER]
    assert (await _library_entry(api, "welcome"))["to_send"] == 1


async def _library_entry(api, kind):
    return {a["kind"]: a for a in (await api.get("/api/actions")).json()["actions"]}[kind]


async def test_marking_needs_the_action_on_and_approved(signed_in, stripe_data, api):
    await signed_in()
    await api.patch("/api/actions/welcome", json={"enabled": True})
    resp = await api.post("/api/actions/welcome/outreach", json={"customer_id": customer_id(NEW), "status": "sent"})
    assert resp.status_code == 400
    welcome = await _library_entry(api, "welcome")
    assert (welcome["enabled"], welcome["open"], welcome["to_send"]) == (True, False, 0)  # not approved yet


async def test_missing_values_are_flagged(signed_in, stripe_data, api):
    await signed_in()
    await api.patch("/api/actions/welcome", json={"enabled": True, "body": "Read {{substack}}", "approved": True})
    [first, _] = (await api.get("/api/actions/welcome/queue")).json()["customers"]
    assert first["note"]["missing"] == ["substack"]


async def test_writers_never_see_each_others_outreach(signed_in, stripe_data, api):
    await signed_in()
    await _open_welcome(api)
    sent = (await api.post("/api/actions/welcome/outreach", json={"customer_id": customer_id(NEW), "status": "sent"})).json()

    await signed_in()
    assert (await api.get("/api/outreach/contacted")).json()["contacted"] == {}
    assert (await api.get(f"/api/customers/{customer_id(NEW)}/outreach")).json()["outreach"] == []
    assert (await api.get("/api/actions/welcome/queue")).json()["open"] is False
    assert (await api.delete(f"/api/outreach/{sent['id']}")).status_code == 404


async def test_first_names_with_a_fallback(signed_in, stripe_data, api):
    await signed_in()
    await api.patch("/api/actions/welcome", json={"enabled": True, "body": "Hi {{first_name}},", "approved": True})
    jane, other = (await api.get("/api/actions/welcome/queue")).json()["customers"]
    assert jane["note"]["body"][1] == {"text": "Jane", "field": "first_name", "fallback": False}
    assert other["note"]["body"][1] == {"text": "there", "field": "first_name", "fallback": True}
    assert other["note"]["missing"] == []  # the fallback covers it


async def test_notes_are_stored_encrypted(signed_in, stripe_data, api, db):
    await signed_in()
    await _open_welcome(api)
    await api.post("/api/actions/welcome/outreach", json={
        "customer_id": customer_id(NEW), "status": "sent", "subject": "Hi Jane", "body": "Dear Jane, thank you",
    })
    async with db() as session:
        [row] = (await session.execute(text("SELECT * FROM outreach"))).mappings().all()
    assert b"Jane" not in bytes(row["note_ciphertext"]) and "Jane" not in str(dict(row))
    [stored] = (await api.get("/api/actions/welcome/outreach")).json()["outreach"]
    assert (stored["subject"], stored["body"]) == ("Hi Jane", "Dear Jane, thank you")


async def test_preview_fills_an_unsaved_draft_for_real_readers(signed_in, stripe_data, api):
    await signed_in()  # the action is off and nothing is approved: previewing doesn't need either
    resp = await api.post("/api/actions/welcome/preview", json={"subject": "Hi {{first_name}}", "body": "{{plan}}!"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["example"] is False
    jane, other = data["readers"]
    assert jane["email"] == NEW and jane["note"]["subject"][1] == {"text": "Jane", "field": "first_name", "fallback": False}
    assert other["note"]["subject"][1] == {"text": "there", "field": "first_name", "fallback": True}
    # Nothing was saved.
    assert (await api.get("/api/actions/welcome")).json()["template"]["is_default"] is True


async def test_preview_uses_an_example_reader_when_nobody_is_in_the_audience(signed_in, stripe_data, api):
    await signed_in()
    data = (await api.post("/api/actions/save/preview", json={"subject": "", "body": "Hi {{first_name}}, {{ends}} {{substack}}"})).json()
    assert data["example"] is True
    (reader,) = data["readers"]
    assert reader["email"] is None
    assert "".join(p["text"] for p in reader["note"]["body"]) == "Hi Sam, October 20 "
    assert reader["note"]["missing"] == ["substack"]  # the writer's own settings are real, not examples


async def test_preview_of_an_unknown_action(signed_in, stripe_data, api):
    await signed_in()
    assert (await api.post("/api/actions/nope/preview", json={})).status_code == 404
