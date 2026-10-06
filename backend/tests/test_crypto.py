"""Encryption at rest for stored Stripe keys."""

import os

import pytest

from app import crypto
from app.config import get_settings
from app.crypto import DecryptionError, KmsCipher, LocalCipher, Sealed

KEY = "rk_live_" + "x" * 90 + "a1b2"


async def test_round_trip_and_nothing_readable_at_rest():
    cipher = LocalCipher(os.urandom(32))
    sealed = await cipher.encrypt(KEY, "stripe_credential:u1:c1")

    assert KEY.encode() not in sealed.ciphertext + sealed.wrapped_dek
    assert b"a1b2" not in sealed.ciphertext
    assert await cipher.decrypt(sealed, "stripe_credential:u1:c1") == KEY
    # A fresh data key and nonce each time: the same key never encrypts to the same bytes.
    assert (await cipher.encrypt(KEY, "stripe_credential:u1:c1")).ciphertext != sealed.ciphertext


async def test_ciphertext_moved_to_another_record_or_user_fails():
    cipher = LocalCipher(os.urandom(32))
    sealed = await cipher.encrypt(KEY, "stripe_credential:u1:c1")
    for aad in ["stripe_credential:u2:c1", "stripe_credential:u1:c2"]:
        with pytest.raises(DecryptionError):
            await cipher.decrypt(sealed, aad)


async def test_wrong_master_key_fails():
    sealed = await LocalCipher(os.urandom(32)).encrypt(KEY, "a")
    with pytest.raises(DecryptionError):
        await LocalCipher(os.urandom(32)).decrypt(sealed, "a")


async def test_tampered_ciphertext_fails():
    cipher = LocalCipher(os.urandom(32))
    sealed = await cipher.encrypt(KEY, "a")
    flipped = sealed.ciphertext[:-1] + bytes([sealed.ciphertext[-1] ^ 1])
    with pytest.raises(DecryptionError):
        await cipher.decrypt(Sealed(flipped, sealed.wrapped_dek, sealed.cipher), "a")


async def test_other_scheme_is_refused():
    cipher = LocalCipher(os.urandom(32))
    sealed = await cipher.encrypt(KEY, "a")
    with pytest.raises(DecryptionError, match="sealed with"):
        await cipher.decrypt(Sealed(sealed.ciphertext, sealed.wrapped_dek, "aws-kms-aesgcm-v1"), "a")


def test_master_key_is_never_in_repr():
    master = os.urandom(32)
    assert master.hex() not in repr(LocalCipher(master))


def test_generated_master_key_is_persisted_and_private(tmp_path, monkeypatch):
    path = tmp_path / ".stoke_encryption_key"
    monkeypatch.setenv("STOKE_ENCRYPTION_KEY", "")
    monkeypatch.setenv("ENCRYPTION_KEY_FILE", str(path))
    get_settings.cache_clear()
    crypto.get_cipher.cache_clear()

    crypto.get_cipher()
    assert len(path.read_text()) == 64 and path.stat().st_mode & 0o777 == 0o600


class FakeKms:
    """Stands in for boto3's KMS client: wraps data keys under a key only it holds."""

    def __init__(self):
        self._inner = LocalCipher(os.urandom(32))
        self.calls = []

    def generate_data_key(self, KeyId, KeySpec, EncryptionContext):
        self.calls.append(("generate", EncryptionContext))
        dek = os.urandom(32)
        wrapped = crypto._seal(self._inner._master, dek, EncryptionContext["aad"].encode())
        return {"Plaintext": dek, "CiphertextBlob": wrapped}

    def decrypt(self, CiphertextBlob, EncryptionContext):
        self.calls.append(("decrypt", EncryptionContext))
        return {"Plaintext": crypto._open(self._inner._master, CiphertextBlob, EncryptionContext["aad"].encode())}


async def test_kms_envelope():
    kms = FakeKms()
    cipher = KmsCipher("alias/stoke", client=kms)
    sealed = await cipher.encrypt(KEY, "stripe_credential:u1:c1")

    assert KEY.encode() not in sealed.ciphertext + sealed.wrapped_dek
    assert await cipher.decrypt(sealed, "stripe_credential:u1:c1") == KEY
    assert kms.calls == [("generate", {"aad": "stripe_credential:u1:c1"}), ("decrypt", {"aad": "stripe_credential:u1:c1"})]
    with pytest.raises(DecryptionError):
        await cipher.decrypt(sealed, "stripe_credential:u2:c1")
