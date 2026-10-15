"""Free subscribers uploaded from a Substack export, and the Free -> paid action they feed."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from app import actions, substack_list
from app.customer_id import customer_id
from app.substack_list import SubstackListError
from tests.test_outreach import NEW, api, signed_in, stripe_data  # noqa: F401 (fixtures)

HEADER = (
    "Email,Name,Type,Activity,Start date,Revenue,Comments,Comments (7d),Comments (30d),Shares,Shares (7d),Shares (30d),"
    "Country,State/Province,Time zone,Emails received (6mo),Emails dropped (6mo),num_emails_opened,Emails opened (6mo),"
    "Emails opened (7d),Emails opened (30d),Last email open,Links clicked,Last clicked at,Video plays (30d),"
    "Unique videos played (30d),Last video played,Podcast plays (30d),Unique podcasts played (30d),Last podcast played,"
    "Unique emails seen (6mo),Unique emails seen (7d),Unique emails seen (30d),Post views,Post views (7d),"
    "Post views (30d),Unique posts seen,Unique posts seen (7d),Unique posts seen (30d),Subscriptions gifted,"
    "Expiration date,Subscription source (free),Subscription source (paid),Days active (30d),First paid date,"
    "Paid upgrade date,Cancel date,Cancel reason,Cancel feedback,Bestseller,Stripe plan,Sections,Group membership"
)
COLUMNS = HEADER.split(",")


def row(email, name, type_, start, **values) -> str:
    cells = dict.fromkeys(COLUMNS, "0") | {
        "Email": email, "Name": name, "Type": type_, "Start date": start, "Revenue": "$0.00",
        "Sections": '"Writer’s Substack,"', "Group membership": "None",
    } | {k: str(v) for k, v in values.items()}
    return ",".join(cells[c] for c in COLUMNS)


# Shaped like a real export: an author, two free subscribers and a paying one.
EXPORT = "\n".join([
    HEADER,
    row("author@example.com", "Writer Person", "Author", "2023-06-26T18:05:33.417Z"),
    row("Evan@Example.com", "Evan Agovino", "Free", "2025-01-07T16:53:29.137Z", **{
        "Activity": 4, "Emails received (6mo)": 20, "Emails opened (6mo)": 15, "Days active (30d)": 6, "Comments": 2,
    }),
    row("paid@example.com", "Paid Reader", "Monthly Subscriber", "2026-09-24T15:50:25.679Z"),
    row("fresh@example.com", "", "Free", "2026-10-07T19:13:22.797Z", **{"Links clicked": ""}),
])
FILENAME = "subscriber-export-2026-10-15-15-20-00.csv"


def test_parse_keeps_free_subscribers_only():
    export = substack_list.parse(FILENAME, "﻿" + EXPORT)
    assert export.exported_at == datetime(2026, 10, 15, 15, 20, tzinfo=UTC)
    assert [s.email for s in export.free] == ["evan@example.com", "fresh@example.com"]
    evan, fresh = export.free
    assert (evan.first_name, evan.activity, evan.emails_received_6mo, evan.emails_opened_6mo, evan.days_active_30d,
            evan.comments) == ("Evan", 4, 20, 15, 6, 2)
    assert evan.started == int(datetime(2025, 1, 7, 16, 53, 29, 137000, tzinfo=UTC).timestamp())
    assert (fresh.first_name, fresh.links_clicked) == (None, 0)  # blanks read as 0


def test_export_time_falls_back_to_the_upload():
    now = datetime(2026, 10, 16, tzinfo=UTC)
    assert substack_list.parse("subscribers.csv", EXPORT, now).exported_at == now


def test_a_file_that_isnt_an_export_is_refused_without_echoing_it():
    with pytest.raises(SubstackListError) as exc:
        substack_list.parse(FILENAME, "email,secret\nada@example.com,SENSITIVE")
    assert "SENSITIVE" not in str(exc.value) and "ada@" not in str(exc.value)


LISTS = "/api/substack/subscribers"


async def test_upload_replace_and_remove(signed_in, api, db):  # noqa: F811
    await signed_in()
    assert (await api.get(LISTS)).json() == []
    resp = await api.put(f"{LISTS}/verticals", json={"filename": FILENAME, "csv": EXPORT})
    assert resp.status_code == 200, resp.text
    assert resp.json()["publication"] == "verticals" and resp.json()["free_count"] == 2
    assert resp.json()["exported_at"] == int(datetime(2026, 10, 15, 15, 20, tzinfo=UTC).timestamp())

    async with db() as session:
        rows = (await session.execute(text("SELECT * FROM substack_subscribers"))).mappings().all()
    assert len(rows) == 2
    assert all(b"example.com" not in bytes(r["email"]) for r in rows) and "Evan" not in str([dict(r) for r in rows])

    again = "\n".join([HEADER, row("other@example.com", "Other", "Free", "2025-01-01T00:00:00Z")])
    assert (await api.put(f"{LISTS}/verticals", json={"filename": "x.csv", "csv": again})).json()["free_count"] == 1
    async with db() as session:
        assert await session.scalar(text("SELECT count(*) FROM substack_subscribers")) == 1

    bad = await api.put(f"{LISTS}/verticals", json={"filename": "x.csv", "csv": "a,b\n1,2"})
    assert bad.status_code == 400
    assert (await api.put(f"{LISTS}/Not.A.Subdomain", json={"filename": FILENAME, "csv": EXPORT})).status_code == 422

    assert (await api.delete(f"{LISTS}/verticals")).status_code == 204
    assert (await api.get(LISTS)).json() == []
    async with db() as session:
        assert await session.scalar(text("SELECT count(*) FROM substack_subscribers")) == 0


async def test_each_publication_has_its_own_list(signed_in, api, db):  # noqa: F811
    user = await signed_in()
    older = "subscriber-export-2026-09-01-00-00-00.csv"
    second = "\n".join([
        HEADER,
        row("evan@example.com", "Evan", "Free", "2024-01-01T00:00:00Z", Activity=1),  # less engaged here
        row("only@example.com", "Only", "Free", "2025-01-01T00:00:00Z"),
    ])
    await api.put(f"{LISTS}/verticals", json={"filename": FILENAME, "csv": EXPORT})
    await api.put(f"{LISTS}/sidebar", json={"filename": older, "csv": second})
    assert [(x["publication"], x["free_count"]) for x in (await api.get(LISTS)).json()] == [("sidebar", 2), ("verticals", 2)]

    # Replacing one leaves the other.
    await api.put(f"{LISTS}/sidebar", json={"filename": older, "csv": second})
    async with db() as session:
        assert await session.scalar(text("SELECT count(*) FROM substack_subscribers")) == 4

        # Ranked together, each reader once, by the publication they're more engaged with; as fresh as the oldest.
        free = await substack_list.load(session, user)
    assert free.exported_at == datetime(2026, 9, 1, tzinfo=UTC)
    assert sorted(s.email for s in free.subscribers) == ["evan@example.com", "fresh@example.com", "only@example.com"]
    assert next(s for s in free.subscribers if s.email == "evan@example.com").activity == 4

    assert (await api.delete(f"{LISTS}/verticals")).status_code == 204
    assert [x["publication"] for x in (await api.get(LISTS)).json()] == ["sidebar"]


async def test_writers_never_see_each_others_list(signed_in, api):  # noqa: F811
    await signed_in()
    await api.put(f"{LISTS}/verticals", json={"filename": FILENAME, "csv": EXPORT})
    await signed_in()
    assert (await api.get(LISTS)).json() == []


def _many(n: int) -> str:
    """n free subscribers, reader0 the most engaged."""
    return "\n".join([HEADER] + [
        row(f"reader{i}@example.com", "Sam Reader", "Free", "2025-01-01T00:00:00Z", **{"Days active (30d)": max(15 - i, 0)})
        for i in range(n)
    ])


async def test_free_to_paid_offers_a_batch_at_a_time(signed_in, stripe_data, api):  # noqa: F811
    await signed_in()
    await api.put(f"{LISTS}/verticals", json={"filename": FILENAME, "csv": _many(actions.FREE_BATCH + 5)})
    assert (await api.patch("/api/actions/free-to-paid", json={"enabled": True, "approved": True})).status_code == 204

    action = (await api.get("/api/actions/free-to-paid")).json()
    assert len(action["customers"]) == actions.FREE_BATCH + 5  # the whole ranked pool
    assert action["customers"][0]["email"] == "reader0@example.com" and action["customers"][0]["score"] > 0
    assert (action["action"]["to_send"], action["action"]["batch"]) == (actions.FREE_BATCH, actions.FREE_BATCH)

    queue = (await api.get("/api/actions/free-to-paid/queue")).json()["customers"]
    assert len(queue) == actions.FREE_BATCH
    assert queue[0]["account_id"] == "substack"
    assert {"text": "Sam", "field": "first_name", "fallback": False} in queue[0]["note"]["body"]

    outside = customer_id(f"reader{actions.FREE_BATCH}@example.com")
    refused = await api.post("/api/actions/free-to-paid/outreach", json={"customer_id": outside, "status": "sent"})
    assert refused.status_code == 400

    skipped = await api.post("/api/actions/free-to-paid/outreach", json={
        "customer_id": customer_id("reader0@example.com"), "status": "skipped",
    })
    assert skipped.status_code == 201 and skipped.json()["email"] == "reader0@example.com"
    queue = (await api.get("/api/actions/free-to-paid/queue")).json()["customers"]
    assert len(queue) == actions.FREE_BATCH and queue[-1]["customer_id"] == outside  # the next one moves up
    assert (await api.post("/api/actions/free-to-paid/outreach", json={"customer_id": outside, "status": "sent"})).status_code == 201


async def test_free_to_paid_leaves_out_stripe_payers(signed_in, stripe_data, api):  # noqa: F811
    await signed_in()
    csv = "\n".join([HEADER, row(NEW, "New", "Free", "2025-01-01T00:00:00Z"), row("free@example.com", "", "Free", "2025-01-01T00:00:00Z")])
    await api.put(f"{LISTS}/verticals", json={"filename": FILENAME, "csv": csv})
    action = (await api.get("/api/actions/free-to-paid")).json()
    assert [c["email"] for c in action["customers"]] == ["free@example.com"]
