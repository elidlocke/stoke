"""Encryption at rest for stored Stripe keys: envelope encryption with AES-256-GCM.

Each record gets its own random data key (DEK). The Stripe key is encrypted with the DEK, and the
DEK is encrypted ("wrapped") with a master key. Only the ciphertext and the wrapped DEK are stored,
so a database dump or backup alone reveals nothing.

Both layers bind associated data (the owner and record ids): ciphertext copied onto another row or
another user's account fails to decrypt instead of quietly working there.

Master key:
- "local": a 32-byte key from STOKE_ENCRYPTION_KEY (hex). For development and simple hosts.
- "aws_kms": the master key lives in AWS KMS and never leaves it. KMS generates and unwraps each
  DEK (using the associated data as its encryption context), and every unwrap is permissioned and
  logged by CloudTrail. Needs the `kms` extra (boto3) and AWS_KMS_KEY_ID.
"""

import asyncio
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

NONCE_BYTES = 12


@dataclass(frozen=True)
class Sealed:
    ciphertext: bytes
    wrapped_dek: bytes
    cipher: str  # which scheme sealed it, so records can be re-encrypted after a master key change


class DecryptionError(Exception):
    pass


class MissingSecret(RuntimeError):
    def __init__(self, name: str):
        super().__init__(
            f"{name} isn't set. Generate one with "
            "`python3 -c 'import secrets; print(secrets.token_hex(32))'` and add it to .env "
            "(or the host's environment). Back it up: changing it later breaks existing data."
        )


class KeyCipher(Protocol):
    name: str

    async def encrypt(self, plaintext: str, aad: str) -> Sealed: ...

    async def decrypt(self, sealed: Sealed, aad: str) -> str: ...


def _seal(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def _open(key: bytes, blob: bytes, aad: bytes) -> bytes:
    try:
        return AESGCM(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], aad)
    except Exception as exc:  # InvalidTag, or a malformed blob
        raise DecryptionError("Stored key can't be decrypted") from exc


def _check_scheme(sealed: Sealed, name: str) -> None:
    if sealed.cipher != name:
        raise DecryptionError(f"Stored key was sealed with {sealed.cipher}, but KEY_CIPHER is {name}")


class LocalCipher:
    name = "local-aesgcm-v1"

    def __init__(self, master_key: bytes):
        if len(master_key) != 32:
            raise ValueError("The encryption key must be 32 bytes (64 hex characters)")
        self._master = master_key

    def __repr__(self) -> str:
        return "LocalCipher(<redacted>)"

    async def encrypt(self, plaintext: str, aad: str) -> Sealed:
        dek = AESGCM.generate_key(bit_length=256)
        return Sealed(
            ciphertext=_seal(dek, plaintext.encode(), aad.encode()),
            wrapped_dek=_seal(self._master, dek, aad.encode()),
            cipher=self.name,
        )

    async def decrypt(self, sealed: Sealed, aad: str) -> str:
        _check_scheme(sealed, self.name)
        dek = _open(self._master, sealed.wrapped_dek, aad.encode())
        return _open(dek, sealed.ciphertext, aad.encode()).decode()


class KmsCipher:
    name = "aws-kms-aesgcm-v1"

    def __init__(self, key_id: str, client=None):
        if client is None:
            import boto3  # optional dependency: `uv sync --extra kms`

            client = boto3.client("kms")
        self._key_id = key_id
        self._kms = client

    async def encrypt(self, plaintext: str, aad: str) -> Sealed:
        resp = await asyncio.to_thread(
            self._kms.generate_data_key, KeyId=self._key_id, KeySpec="AES_256", EncryptionContext={"aad": aad}
        )
        return Sealed(
            ciphertext=_seal(resp["Plaintext"], plaintext.encode(), aad.encode()),
            wrapped_dek=resp["CiphertextBlob"],
            cipher=self.name,
        )

    async def decrypt(self, sealed: Sealed, aad: str) -> str:
        _check_scheme(sealed, self.name)
        try:
            resp = await asyncio.to_thread(
                self._kms.decrypt, CiphertextBlob=sealed.wrapped_dek, EncryptionContext={"aad": aad}
            )
        except Exception as exc:
            raise DecryptionError("Stored key can't be decrypted") from exc
        return _open(resp["Plaintext"], sealed.ciphertext, aad.encode()).decode()


@lru_cache
def get_cipher() -> KeyCipher:
    settings = get_settings()
    if settings.key_cipher == "aws_kms":
        if not settings.aws_kms_key_id:
            raise RuntimeError("KEY_CIPHER=aws_kms needs AWS_KMS_KEY_ID")
        return KmsCipher(settings.aws_kms_key_id)
    # An empty value (as in .env.example) means unset.
    if not (settings.stoke_encryption_key and (hex_key := settings.stoke_encryption_key.get_secret_value())):
        raise MissingSecret("STOKE_ENCRYPTION_KEY")
    return LocalCipher(bytes.fromhex(hex_key))
