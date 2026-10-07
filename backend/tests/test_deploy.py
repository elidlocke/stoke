"""Settings and serving that the production image relies on."""

import importlib

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings


@pytest.mark.parametrize("url", [
    "postgres://u:p@db.internal:5432/stoke",
    "postgresql://u:p@db.internal:5432/stoke",
    "postgresql+asyncpg://u:p@db.internal:5432/stoke",
])
def test_database_url_uses_asyncpg(monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)
    assert get_settings().database_url == "postgresql+asyncpg://u:p@db.internal:5432/stoke"


@pytest.fixture
def served(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-abc.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path.parent / "secret.txt").write_text("outside")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield TestClient(importlib.reload(main).app)
    monkeypatch.delenv("STATIC_DIR")
    get_settings.cache_clear()
    importlib.reload(main)


def test_serves_the_frontend(served):
    assert served.get("/assets/index-abc.js").text == "console.log(1)"
    assert served.get("/favicon.svg").text == "<svg/>"
    # Client-side routes get the app shell.
    for path in ("/", "/settings", "/customers/0123abcd"):
        assert served.get(path).text == "<div id=root></div>"
    assert served.get("/api/healthz").json() == {"ok": True}
    # Unknown API paths stay JSON 404s, and nothing outside the build is reachable.
    assert served.get("/api/nope").status_code == 404
    assert served.get("/..%2Fsecret.txt").text == "<div id=root></div>"
