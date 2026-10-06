from app import customer_id as cid
from app import secret_file
from app.config import get_settings


def test_ids_are_opaque_stable_and_keyed(monkeypatch):
    a = cid.customer_id("ada@example.com")
    assert len(a) == cid.ID_LENGTH and all(ch in "0123456789abcdef" for ch in a)
    assert "ada" not in a and a == cid.customer_id("ada@example.com")
    assert a != cid.customer_id("bob@example.com")

    # Independent of API keys: rotating them doesn't change ids.
    monkeypatch.setenv("STRIPE_API_KEY", "rk_test_rotated")
    monkeypatch.setenv("STRIPE_ACCOUNT_KEYS", "rk_test_new_creator")
    get_settings.cache_clear()
    assert cid.customer_id("ada@example.com") == a

    # A different key gives different ids, so they can't be recomputed from a guessed email.
    monkeypatch.setenv("CUSTOMER_ID_SECRET", "another key")
    get_settings.cache_clear()
    assert cid.customer_id("ada@example.com") != a

    # Empty, as copied from .env.example, falls back to the generated key rather than an empty one.
    monkeypatch.setenv("CUSTOMER_ID_SECRET", "")
    get_settings.cache_clear()
    assert cid.customer_id("ada@example.com") == a


def test_resolve():
    a = cid.customer_id("ada@example.com")
    assert cid.resolve(a, ["bob@x.com", None, "ada@example.com"]) == "ada@example.com"
    assert cid.resolve(a, ["bob@x.com"]) is None


def test_generated_key_is_persisted_and_private(tmp_path, monkeypatch):
    path = tmp_path / ".customer_id_secret"
    monkeypatch.setenv("CUSTOMER_ID_SECRET_FILE", str(path))
    get_settings.cache_clear()
    a = cid.customer_id("ada@example.com")
    assert len(path.read_text()) == 64 and path.stat().st_mode & 0o777 == 0o600

    secret_file._cache.clear()  # as after a restart
    assert cid.customer_id("ada@example.com") == a
