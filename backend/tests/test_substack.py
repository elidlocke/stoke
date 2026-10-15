"""The writer's Substack profile, and the links Stoke suggests from it."""

import httpx
import pytest

from app import substack
from app.auth import current_user
from app.main import app

# Trimmed from substack.com/api/v1/user/sarahfay/public_profile: her profile's "chips" are her two
# publications, one with a custom domain (sarahfay.org).
SARAH = {
    "name": "Sarah Fay, PhD",
    "handle": "sarahfay",
    "photo_url": "https://substack-post-media.s3.amazonaws.com/public/images/sarah.png",
    "userLinks": [],
    "publicationUsers": [
        {"role": "admin", "publication": {
            "id": 1, "name": "Substack Writers at Work", "subdomain": "yourexpertguide",
            "custom_domain": "www.substackwritersatwork.com",
        }},
        {"role": "admin", "publication": {
            "id": 2, "name": "Less & Less of More & More", "subdomain": "sarahfay", "custom_domain": "www.sarahfay.org",
        }},
        {"role": "contributor", "publication": {"id": 3, "name": "Someone else's", "subdomain": "else"}},
    ],
    "primaryPublication": {"id": 1, "name": "Substack Writers at Work", "subdomain": "yourexpertguide"},
}
# As on substack.com/@noahpinion, plus links to where readers can pay.
NOAH = {
    "name": "Noah Smith",
    "userLinks": [
        {"value": "Noahpinion", "type": "twitter", "label": None, "url": "https://x.com/Noahpinion"},
        {"type": "website", "label": "Office hours", "url": "https://calendly.com/noah/office-hours?utm_source=substack"},
        {"type": "website", "label": None, "url": "https://noahpinion.blog/?utm_campaign=profile_chips&ref=1"},
        {"type": "unknown", "url": "not a link"},
    ],
    "publicationUsers": [{"role": "admin", "publication": {"id": 9, "name": "Noahpinion", "subdomain": "noahpinion"}}],
}


def as_tuples(links):
    return [(s.category, s.kind, s.name, s.url, s.purchase) for s in links]


@pytest.mark.parametrize("typed", ["sarahfay", "@SarahFay", " https://substack.com/@sarahfay ", "substack.com/@sarahfay/posts"])
def test_parse_handle(typed):
    assert substack.parse_handle(typed) == "sarahfay"


@pytest.mark.parametrize("typed", ["", "@", "sarah fay", "https://sarahfay.substack.com"])
def test_parse_handle_rejects_what_isnt_one(typed):
    with pytest.raises(substack.SubstackError):
        substack.parse_handle(typed)


def test_publications_the_writer_runs_are_substack_links():
    assert as_tuples(substack.suggestions(SARAH)) == [
        ("social", "substack", "Substack Writers at Work", "https://www.substackwritersatwork.com", None),
        ("social", "substack", "Less & Less of More & More", "https://www.sarahfay.org", None),
    ]


def test_user_links_are_sorted_into_channels_and_revenue_streams():
    assert as_tuples(substack.suggestions(NOAH)) == [
        ("social", "substack", "Noahpinion", "https://noahpinion.substack.com", None),
        ("social", "x", None, "https://x.com/Noahpinion", None),
        ("revenue_source", "calendly", "Office hours", "https://calendly.com/noah/office-hours", "repeat"),
        ("social", "website", None, "https://noahpinion.blog/?ref=1", None),
    ]


def test_books_are_revenue_streams_named_by_title():
    data = {"userLinks": [
        # As on substack.com/@substoke: Substack's "books" chip, titled in its value.
        {"type": "books", "label": "Books", "value": "The Super Powers in Your Fruit and Veggies",
         "url": "https://bookshop.org/p/books/the-super-powers/f0f2?ean=9798285848646"},
        {"type": "books", "label": "Books", "value": "Second Book", "url": "https://www.amazon.com/dp/B0TEST"},
        {"type": "website", "label": None, "url": "https://bookshop.org/p/books/third"},
    ]}
    assert as_tuples(substack.suggestions(data)) == [
        ("revenue_source", "book", "The Super Powers in Your Fruit and Veggies",
         "https://bookshop.org/p/books/the-super-powers/f0f2?ean=9798285848646", "once"),
        ("revenue_source", "book", "Second Book", "https://www.amazon.com/dp/B0TEST", "once"),
        ("revenue_source", "book", "Book", "https://bookshop.org/p/books/third", "once"),
    ]


def test_same_link_ignores_scheme_www_and_trailing_slash():
    assert substack.same_link("https://www.sarahfay.org/", "http://sarahfay.org")
    assert not substack.same_link("https://sarahfay.org/a", "https://sarahfay.org/b")


# ---- Through the API ----


@pytest.fixture
async def api():
    substack.clear_cache()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


def profile_url(handle):
    return substack.PROFILE_URL.format(handle=handle)


async def test_save_a_handle_and_add_its_links(db, make_user, api, respx_mock):
    user = await make_user()
    app.dependency_overrides[current_user] = lambda: user
    respx_mock.get(profile_url("sarahfay")).respond(json=SARAH)

    assert (await api.get("/api/substack")).json() == {
        "handle": None, "profile": None, "suggestions": [], "publications": [], "error": None,
    }
    out = (await api.put("/api/substack", json={"handle": "@sarahfay"})).json()
    assert out["handle"] == "sarahfay" and out["error"] is None
    assert out["profile"]["url"] == "https://substack.com/@sarahfay"
    assert out["publications"] == [  # the ones she runs, primary first; not the one she contributes to
        {"subdomain": "yourexpertguide", "name": "Substack Writers at Work", "url": "https://www.substackwritersatwork.com"},
        {"subdomain": "sarahfay", "name": "Less & Less of More & More", "url": "https://www.sarahfay.org"},
    ]
    assert [s["url"] for s in out["suggestions"]] == ["https://www.substackwritersatwork.com", "https://www.sarahfay.org"]

    # Once added, a link is no longer suggested.
    added = {k: v for k, v in out["suggestions"][1].items() if k != "purchase"}
    assert (await api.post("/api/links", json=added)).status_code == 201
    out = (await api.get("/api/substack")).json()
    assert [s["url"] for s in out["suggestions"]] == ["https://www.substackwritersatwork.com"]

    # The currency setting is kept alongside it.
    assert (await api.put("/api/settings", json={"reporting_currency": "EUR"})).status_code == 200
    assert (await api.get("/api/substack")).json()["handle"] == "sarahfay"

    # Saving the handle again reads the profile again, e.g. after the writer adds a link to it.
    respx_mock.get(profile_url("sarahfay")).respond(json=SARAH | {"userLinks": [
        {"type": "linkedin", "label": "LinkedIn", "url": "https://www.linkedin.com/in/sarahfay/"},
    ]})
    assert (await api.get("/api/substack")).json()["suggestions"][-1]["kind"] != "linkedin"  # within the hour
    out = (await api.put("/api/substack", json={"handle": "sarahfay"})).json()
    assert out["suggestions"][-1] == {
        "category": "social", "kind": "linkedin", "name": "LinkedIn", "url": "https://www.linkedin.com/in/sarahfay/",
        "purchase": None,
    }

    assert (await api.put("/api/substack", json={"handle": None})).json()["handle"] is None


async def test_a_handle_with_no_profile_isnt_saved(db, make_user, api, respx_mock):
    user = await make_user()
    app.dependency_overrides[current_user] = lambda: user
    respx_mock.get(profile_url("nobody")).respond(404)
    resp = await api.put("/api/substack", json={"handle": "nobody"})
    assert resp.status_code == 400 and "@nobody" in resp.json()["detail"]
    assert (await api.put("/api/substack", json={"handle": "not a handle"})).status_code == 400
    assert (await api.get("/api/substack")).json()["handle"] is None


@pytest.mark.parametrize("response", [
    httpx.Response(500), httpx.Response(200, text="<html>"), httpx.Response(200, json=["unexpected"]),
    httpx.ConnectTimeout("slow"),
])
async def test_when_substack_cant_be_read_the_handle_is_kept(db, make_user, api, respx_mock, response):
    user = await make_user()
    app.dependency_overrides[current_user] = lambda: user
    route = respx_mock.get(profile_url("sarahfay"))
    route.mock(side_effect=response) if isinstance(response, Exception) else route.mock(return_value=response)
    out = (await api.put("/api/substack", json={"handle": "sarahfay"})).json()
    assert (out["handle"], out["profile"], out["suggestions"]) == ("sarahfay", None, [])
    assert out["error"] == substack.UNAVAILABLE
