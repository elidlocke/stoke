"""Connecting Gmail, test notes to the writer, and sending from the queue, with Google mocked."""

import base64
import email
import json
from email.policy import default as default_policy
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
import respx
from sqlalchemy import text

from app import gmail
from app.customer_id import customer_id
from tests.test_outreach import NEW, NEWER, _open_welcome, api, signed_in, stripe_data  # noqa: F401

CLIENT_ID = "stoke-test.apps.googleusercontent.com"
WRITER = "writer@gmail.com"


def _id_token(email_address=WRITER, aud=CLIENT_ID):
    return jwt.encode({"aud": aud, "email": email_address, "email_verified": True, "sub": "1"}, "x" * 32, algorithm="HS256")


def _tokens(**overrides):
    return {
        "access_token": "ya29.access", "expires_in": 3599, "refresh_token": "1//refresh", "token_type": "Bearer",
        "scope": f"openid {gmail.SEND_SCOPE} https://www.googleapis.com/auth/userinfo.email",
        "id_token": _id_token(),
    } | overrides


@pytest.fixture
def google():
    with respx.mock(assert_all_called=False) as mock:
        mock.sent = []

        def send(request):
            mock.sent.append(email.message_from_bytes(
                base64.urlsafe_b64decode(json.loads(request.content)["raw"] + "=="), policy=default_policy,
            ))
            return httpx.Response(200, json={"id": f"m{len(mock.sent)}", "threadId": f"t{len(mock.sent)}"})

        mock.token = mock.post(gmail.TOKEN_URL).mock(return_value=httpx.Response(200, json=_tokens()))
        mock.send = mock.post(gmail.SEND_URL).mock(side_effect=send)
        mock.revoke = mock.post(gmail.REVOKE_URL).mock(return_value=httpx.Response(200))
        yield mock


async def _connect(api):
    url = (await api.post("/api/gmail/connect")).json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["redirect_uri"] == ["http://localhost:5173/api/gmail/callback"]
    assert set(q["scope"][0].split()) == {"openid", "email", gmail.SEND_SCOPE}
    assert q["code_challenge_method"] == ["S256"] and q["access_type"] == ["offline"]
    return await _callback(api, code="4/code", state=q["state"][0]), q["state"][0]


async def _callback(api, **params) -> str:
    """Google's redirect back: where the API then sends the browser."""
    resp = await api.get("/api/gmail/callback", params=params)
    assert resp.status_code == 303
    return resp.headers["location"]


async def test_connect_stores_the_token_encrypted(signed_in, api, google, db):
    await signed_in()
    assert (await api.get("/api/gmail")).json() == {
        "available": True, "email": None, "status": None, "connected_at": None, "last_sent_at": None,
    }
    location, _ = await _connect(api)
    assert location == "/settings?gmail=connected#gmail"
    gm = (await api.get("/api/gmail")).json()
    assert (gm["email"], gm["status"]) == (WRITER, "ok")
    exchange = parse_qs(google.token.calls.last.request.content.decode())
    assert exchange["grant_type"] == ["authorization_code"] and len(exchange["code_verifier"][0]) >= 43

    async with db() as session:
        [row] = (await session.execute(text("SELECT * FROM gmail_connections"))).mappings().all()
    assert b"1//refresh" not in bytes(row["ciphertext"])

    assert (await api.delete("/api/gmail")).status_code == 204
    assert google.revoke.called
    assert (await api.get("/api/gmail")).json()["email"] is None


async def test_the_flow_must_return_to_the_browser_that_started_it(signed_in, api, google):
    await signed_in()
    url = (await api.post("/api/gmail/connect")).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    tampered = state[:-2] + ("AA" if not state.endswith("AA") else "BB")
    assert await _callback(api, code="4/code", state=tampered) == "/settings?gmail=invalid#gmail"

    api.cookies.clear()  # someone else's browser following the writer's consent link
    assert await _callback(api, code="4/code", state=state) == "/settings?gmail=invalid#gmail"
    assert not google.token.called


async def test_cancelling_at_google(signed_in, api, google):
    await signed_in()
    await api.post("/api/gmail/connect")
    assert await _callback(api, error="access_denied", state="x") == "/settings?gmail=denied#gmail"


async def test_send_permission_must_be_granted(signed_in, api, google):
    await signed_in()
    google.token.mock(return_value=httpx.Response(200, json=_tokens(scope="openid email")))
    location, _ = await _connect(api)
    assert location == "/settings?gmail=no_permission#gmail"
    assert (await api.get("/api/gmail")).json()["email"] is None


async def test_test_note_goes_to_the_writer(signed_in, stripe_data, api, google):
    await signed_in()
    resp = await api.post("/api/actions/welcome/test", json={"subject": "Hi {{first_name}}", "body": "Thanks!"})
    assert resp.status_code == 409 and resp.json()["code"] == "gmail_not_connected"

    await _connect(api)
    # Before approving or turning the action on, from the unsaved draft.
    resp = await api.post("/api/actions/welcome/test", json={"subject": "Hi {{first_name}}", "body": "Thanks, {{first_name}}!"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"to": WRITER, "reader": NEW}
    [msg] = google.sent
    assert msg["To"] == WRITER and msg["Subject"] == "[Test] Hi Jane"
    assert "Thanks, Jane!" in msg.get_content() and NEW in msg.get_content()

    await api.post("/api/actions/welcome/test", json={"subject": "Hi", "body": "{{first_name}}", "customer_id": customer_id(NEWER)})
    assert google.sent[1].get_content().rstrip().endswith("there")  # NEWER has no name: the fallback


async def test_send_from_the_queue(signed_in, stripe_data, api, google):
    await signed_in()
    await _connect(api)
    await _open_welcome(api)
    resp = await api.post("/api/actions/welcome/send", json={
        "customer_id": customer_id(NEW), "subject": "Thanks!\r\nBcc: evil@x.com", "body": "Hello Jane",
    })
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert (out["email"], out["status"], out["via_gmail"]) == (NEW, "sent", True)
    [msg] = google.sent
    assert msg["To"] == NEW and msg["Bcc"] is None and msg["Subject"] == "Thanks! Bcc: evil@x.com"
    assert [c["email"] for c in (await api.get("/api/actions/welcome/queue")).json()["customers"]] == [NEWER]

    again = await api.post("/api/actions/welcome/send", json={"customer_id": customer_id(NEW), "subject": "a", "body": "b"})
    assert again.status_code == 400 and len(google.sent) == 1
    outsider = await api.post("/api/actions/welcome/send", json={"customer_id": "0" * 24, "subject": "a", "body": "b"})
    assert outsider.status_code == 400 and len(google.sent) == 1


async def test_sending_needs_the_action_open(signed_in, stripe_data, api, google):
    await signed_in()
    await _connect(api)
    resp = await api.post("/api/actions/welcome/send", json={"customer_id": customer_id(NEW), "subject": "a", "body": "b"})
    assert resp.status_code == 400 and not google.sent


async def test_a_refused_refresh_token_asks_to_reconnect(signed_in, stripe_data, api, google):
    await signed_in()
    await _connect(api)
    await _open_welcome(api)
    gmail.clear_cache()  # the access token from connecting has expired
    google.token.mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    resp = await api.post("/api/actions/welcome/send", json={"customer_id": customer_id(NEW), "subject": "a", "body": "b"})
    assert resp.status_code == 400 and "Reconnect" in resp.json()["detail"]
    assert (await api.get("/api/gmail")).json()["status"] == "revoked"
    resp = await api.post("/api/actions/welcome/send", json={"customer_id": customer_id(NEW), "subject": "a", "body": "b"})
    assert resp.json()["code"] == "gmail_not_connected"
    assert (await api.get("/api/actions/welcome/queue")).json()["customers"][0]["email"] == NEW  # not marked sent
