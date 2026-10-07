"""Auth0 access tokens: only tokens our tenant issued for our API, unexpired, get in."""

import json
import time

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from app.db_models import User
from app.main import app

ISSUER = "https://stoke-test.auth0.local/"
AUDIENCE = "https://api.stoke.test"
JWKS_URL = "https://stoke-test.auth0.local/.well-known/jwks.json"


def new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks(*keys):
    out = []
    for kid, key in keys:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        out.append(jwk | {"kid": kid, "use": "sig", "alg": "RS256"})
    return {"keys": out}


SIGNING_KEY = new_key()


def token(key=SIGNING_KEY, kid="k1", **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER, "aud": [AUDIENCE, f"{ISSUER}userinfo"], "sub": "auth0|ada",
        "iat": now, "exp": now + 600, "https://stoke/email": "Ada@Example.com",
    } | overrides
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def auth0():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks(("k1", SIGNING_KEY))))
        yield route


@pytest.fixture
async def api():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        yield client


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


async def test_valid_token_creates_the_user_once(db, auth0, api):
    for _ in range(2):
        resp = await api.get("/api/me", headers=bearer(token()))
        assert resp.status_code == 200 and resp.json() == {"email": "ada@example.com"}

    async with db() as session:
        users = list(await session.scalars(select(User)))
    assert [(u.auth_subject, u.email) for u in users] == [("auth0|ada", "ada@example.com")]
    assert auth0.call_count == 1  # signing keys are cached


@pytest.mark.parametrize("bad", [
    token(exp=int(time.time()) - 3600),
    token(iss="https://evil.auth0.com/"),
    token(aud="https://some-other-api"),
    token(key=new_key()),  # right kid, wrong key
    token(sub=None),
    jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "sub": "auth0|ada", "exp": int(time.time()) + 600},
               "shared-secret", algorithm="HS256", headers={"kid": "k1"}),
    "not-a-jwt",
])
async def test_bad_tokens_are_rejected(db, auth0, api, bad):
    resp = await api.get("/api/me", headers=bearer(bad))
    assert resp.status_code == 401 and resp.json() == {"detail": "Not signed in"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer"}])
async def test_missing_token(db, auth0, api, headers):
    assert (await api.get("/api/accounts", headers=headers)).status_code == 401


async def test_rotated_signing_key_is_fetched(db, auth0, api):
    assert (await api.get("/api/me", headers=bearer(token()))).status_code == 200

    rotated = new_key()
    auth0.mock(return_value=httpx.Response(200, json=jwks(("k1", SIGNING_KEY), ("k2", rotated))))
    assert (await api.get("/api/me", headers=bearer(token(key=rotated, kid="k2")))).status_code == 200


async def test_unknown_host_is_rejected(db, auth0):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://evil.example") as client:
        assert (await client.get("/api/me", headers=bearer(token()))).status_code == 400


async def test_health_check_skips_host_check():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://10.0.0.5") as client:
        assert (await client.get("/api/healthz")).json() == {"ok": True}
        assert (await client.get("/api/me")).status_code == 400
