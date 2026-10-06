"""Database tables. API responses are built from app/models.py, never from these classes."""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.crypto import Sealed


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True)}


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    auth_subject: Mapped[str] = mapped_column(Text, unique=True)  # Auth0 `sub`, e.g. "auth0|abc"
    email: Mapped[str | None] = mapped_column(Text)  # lowercased
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # Currency everything is converted to. None: the first account's payout currency.
    reporting_currency: Mapped[str | None] = mapped_column(String(3))


class StripeCredential(Base):
    """A key a user issued from one of their Stripe accounts. The key itself is only stored encrypted."""

    __tablename__ = "stripe_credentials"
    __table_args__ = (UniqueConstraint("user_id", "stripe_account_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str | None] = mapped_column(Text)
    # None when the key can't read its own account (no "Accounts: Read").
    stripe_account_id: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    settlement_currency: Mapped[str] = mapped_column(String(3))
    livemode: Mapped[bool]
    key_type: Mapped[str] = mapped_column(Text)  # "restricted" | "secret"
    key_last4: Mapped[str] = mapped_column(String(4))

    # See app/crypto.py: the key encrypted under a per-record data key, which is itself wrapped
    # by the master key. `cipher` names the scheme, so records can be re-encrypted on rotation.
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    cipher: Mapped[str] = mapped_column(Text)

    status: Mapped[str] = mapped_column(Text)  # "ok" | "missing_permissions" | "invalid"
    missing_permissions: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    last_verified_at: Mapped[datetime] = mapped_column(server_default=func.now())

    @property
    def aad(self) -> str:
        """Associated data binding the encrypted key to this record and its owner."""
        return credential_aad(self.user_id, self.id)

    @property
    def sealed(self) -> Sealed:
        return Sealed(ciphertext=self.ciphertext, wrapped_dek=self.wrapped_dek, cipher=self.cipher)


def credential_aad(user_id: uuid.UUID, credential_id: uuid.UUID) -> str:
    return f"stripe_credential:{user_id}:{credential_id}"
