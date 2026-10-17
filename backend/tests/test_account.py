"""Deleting an account: everything of the writer's goes, and nothing of anyone else's."""

import httpx
import pytest
import respx
from sqlalchemy import func, select

from app import gmail
from app.crypto import get_cipher
from app.db_models import GmailConnection, StripeAccount, StripeCredential, User, WriterLink
from tests.conftest import add_key
from tests.test_credentials import KEY_A, KEY_B, api, as_user, stripe  # noqa: F401


@pytest.fixture
def google():
    with respx.mock(assert_all_called=False) as mock:
        mock.revoke = mock.post(gmail.REVOKE_URL).mock(return_value=httpx.Response(200))
        yield mock


async def _connect_gmail(db, user):
    conn = GmailConnection(user_id=user.id, email="writer@gmail.com", status="ok")
    sealed = await get_cipher().encrypt("1//refresh", conn.aad)
    conn.ciphertext, conn.wrapped_dek, conn.cipher = sealed.ciphertext, sealed.wrapped_dek, sealed.cipher
    async with db() as session:
        session.add(conn)
        await session.commit()


async def _count(db, model, *where) -> int:
    async with db() as session:
        return await session.scalar(select(func.count()).select_from(model).where(*where))


async def test_delete_removes_the_writer_and_their_data(db, make_user, stripe, google, as_user, api):
    writer = await make_user()
    other = await make_user()
    async with db() as session:
        await add_key(session, writer, KEY_A)  # only the writer has acct_a
        await add_key(session, writer, KEY_B)
        await add_key(session, other, KEY_B)  # acct_b is shared with another user
    await _connect_gmail(db, writer)
    as_user(writer)
    assert (await api.post("/api/links", json={
        "category": "social", "kind": "instagram", "url": "https://instagram.com/writer",
    })).status_code == 201
    assert await _count(db, StripeAccount) == 2

    resp = await api.delete("/api/me")
    assert resp.status_code == 204

    assert await _count(db, User, User.id == writer.id) == 0
    assert await _count(db, StripeCredential, StripeCredential.user_id == writer.id) == 0
    assert await _count(db, GmailConnection) == 0
    assert await _count(db, WriterLink) == 0
    assert google.revoke.called
    # acct_a's stored customers go; acct_b's stay, since the other user still reads it.
    assert await _count(db, StripeAccount, StripeAccount.account_id == "acct_a") == 0
    assert await _count(db, StripeAccount, StripeAccount.account_id == "acct_b") == 1
    assert await _count(db, User, User.id == other.id) == 1
    assert await _count(db, StripeCredential, StripeCredential.user_id == other.id) == 1


async def test_responses_are_kept_out_of_search(db, make_user, as_user, api):
    as_user(await make_user())
    assert (await api.get("/api/me")).headers["x-robots-tag"] == "noindex, nofollow"
