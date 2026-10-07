import pytest

from app import customer_id as cid
from app.config import get_settings
from app.crypto import MissingSecret


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


def test_resolve():
    a = cid.customer_id("ada@example.com")
    assert cid.resolve(a, ["bob@x.com", None, "ada@example.com"]) == "ada@example.com"
    assert cid.resolve(a, ["bob@x.com"]) is None


@pytest.mark.parametrize("value", [None, ""])
def test_missing_key_is_an_error(monkeypatch, value):
    # Empty, as copied from .env.example, counts as missing: an empty key would make ids guessable.
    if value is None:
        monkeypatch.delenv("CUSTOMER_ID_SECRET")
    else:
        monkeypatch.setenv("CUSTOMER_ID_SECRET", value)
    get_settings.cache_clear()
    with pytest.raises(MissingSecret, match="CUSTOMER_ID_SECRET"):
        cid.customer_id("ada@example.com")
