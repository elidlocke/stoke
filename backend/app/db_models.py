"""Database tables. API responses are built from app/models.py, never from these classes."""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, ForeignKeyConstraint, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
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
    substack_handle: Mapped[str | None] = mapped_column(Text)  # e.g. "sarahfay", from substack.com/@sarahfay


class StripeCredential(Base):
    """How a user reads one of their Stripe accounts: Stoke's Stripe App installed on it (key_type "oauth", whose
    stored secret is the app's refresh token, see app/stripe_app.py), or, for accounts added before the app, a
    key they issued. The secret is only stored encrypted."""

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
    key_type: Mapped[str] = mapped_column(Text)  # "oauth" | "restricted" | "secret"
    key_last4: Mapped[str | None] = mapped_column(String(4))  # keys only

    # See app/crypto.py: the key (or refresh token) encrypted under a per-record data key, which is itself wrapped
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
    def is_app(self) -> bool:
        """Connected by installing the Stripe App, rather than with a key."""
        return self.key_type == "oauth"

    @property
    def aad(self) -> str:
        """Associated data binding the encrypted key to this record and its owner."""
        return credential_aad(self.user_id, self.id)

    @property
    def sealed(self) -> Sealed:
        return Sealed(ciphertext=self.ciphertext, wrapped_dek=self.wrapped_dek, cipher=self.cipher)


def credential_aad(user_id: uuid.UUID, credential_id: uuid.UUID) -> str:
    return f"stripe_credential:{user_id}:{credential_id}"


def credential_account_id(cred: StripeCredential) -> str:
    """The account a key reads. A key without "Accounts: Read" can't name its account, so its data is
    kept under an id of its own."""
    return cred.stripe_account_id or f"key-{cred.id}"


class StripeAccount(Base):
    """A Stripe account whose objects are stored (see app/sync.py), shared by every user with a key to it."""

    __tablename__ = "stripe_accounts"

    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    livemode: Mapped[bool] = mapped_column(primary_key=True)
    # The stored version reads use, and one being imported to replace it (scripts/resync.py).
    active_version: Mapped[str] = mapped_column(Text)
    target_version: Mapped[str | None] = mapped_column(Text)
    backfilled_at: Mapped[datetime | None]  # when the first import finished; until then, views wait for it
    events_cursor: Mapped[datetime]  # events up to here are reflected in the stored objects
    # The data key that encrypts this account's stored emails, sealed like a Stripe key (app/crypto.py).
    key_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    key_wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    key_cipher: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    @property
    def aad(self) -> str:
        return f"stripe_account:{self.account_id}:{self.livemode}"

    @property
    def sealed_key(self) -> Sealed:
        return Sealed(ciphertext=self.key_ciphertext, wrapped_dek=self.key_wrapped_dek, cipher=self.key_cipher)


class StripeObject(Base):
    """A Stripe object in its stored form: allowlisted fields only, emails encrypted (app/projection.py)."""

    __tablename__ = "stripe_objects"

    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    livemode: Mapped[bool] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(Text, primary_key=True)
    object: Mapped[str] = mapped_column(Text, primary_key=True)  # payment_intent | invoice | subscription | customer
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    created: Mapped[datetime | None]
    data: Mapped[dict] = mapped_column(JSONB)
    # When the read that produced `data` started. An older read never overwrites a newer one.
    fetched_at: Mapped[datetime]


class StripeSyncQueue(Base):
    """Objects to re-read from Stripe, because a webhook or event said they changed."""

    __tablename__ = "stripe_sync_queue"

    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    livemode: Mapped[bool] = mapped_column(primary_key=True)
    object: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    # Reset on every new notice, so a read already in progress doesn't count for a later change.
    enqueued_at: Mapped[datetime]
    claimed_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(default=0)


class StripeBackfill(Base):
    """Progress importing one object type of an account, so an import resumes where it stopped."""

    __tablename__ = "stripe_backfills"

    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    livemode: Mapped[bool] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(Text, primary_key=True)
    object: Mapped[str] = mapped_column(Text, primary_key=True)
    state: Mapped[str] = mapped_column(Text)  # pending | running | done | skipped | failed
    starting_after: Mapped[str | None] = mapped_column(Text)  # the last object stored
    count: Mapped[int] = mapped_column(default=0)
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    retry_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    heartbeat_at: Mapped[datetime | None]


class WriterLink(Base):
    """Something of the writer's to point readers at: a revenue source they sell or a social profile. Entered in Settings; actions use them as their call to action."""

    __tablename__ = "writer_links"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(Text)  # revenue_source | social
    kind: Mapped[str] = mapped_column(Text)  # e.g. coaching, substack_referral, instagram (see app/models.py)
    name: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    # Revenue sources only. The connected account the revenue source is paid through (credential_account_id), so its
    # buyers can be found in Stripe; None: paid somewhere Stoke can't see.
    paid_via_account_id: Mapped[str | None] = mapped_column(Text)
    purchase: Mapped[str | None] = mapped_column(Text)  # revenue sources only: once | repeat | subscription
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class WriterProfile(Base):
    """What the writer has told Stoke about their business, beyond their links. One per user."""

    __tablename__ = "writer_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # Stripe price id -> standard | founding. Unlabeled prices are guessed (see app/actions.py).
    plan_labels: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, server_default="{}")
    # Connect application id -> what its payments are: a revenue source (a WriterLink id), "newsletter", or "other".
    application_labels: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class WriterAction(Base):
    """A writer's settings for one action: on or off, and its note template. Created on first change."""

    __tablename__ = "actions"
    __table_args__ = (UniqueConstraint("user_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(Text)  # e.g. welcome, cross-sell-<link id> (app/actions.py)
    enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    # The note template, with {{merge fields}}; None: the default (app/templates.py).
    subject: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    # When the writer approved the template as it is now. Editing it clears this.
    approved_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Outreach(Base):
    """One note to one person for one action. Identifies them only by their opaque customer id. The note
    itself is encrypted like a Stripe key: it can hold their first name."""

    __tablename__ = "outreach"
    __table_args__ = (UniqueConstraint("user_id", "action_id", "customer_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"))
    customer_id: Mapped[str] = mapped_column(String(24), index=True)  # app/customer_id.py; never the email
    # draft -> approved -> scheduled -> sent (later steps); skipped: left out by the writer.
    status: Mapped[str] = mapped_column(Text)
    # The subject and body as sent, as JSON, sealed with envelope encryption (app/crypto.py).
    note_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    note_wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    note_cipher: Mapped[str] = mapped_column(Text)
    scheduled_for: Mapped[datetime | None]
    sent_at: Mapped[datetime | None]
    converted_at: Mapped[datetime | None]
    # Set when Stoke sent the note from the writer's Gmail; None when the writer sent it themselves.
    gmail_message_id: Mapped[str | None] = mapped_column(Text)
    gmail_thread_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    @property
    def aad(self) -> str:
        """Associated data binding the encrypted note to this record and its owner."""
        return f"outreach:{self.user_id}:{self.id}"

    @property
    def sealed_note(self) -> Sealed:
        return Sealed(ciphertext=self.note_ciphertext, wrapped_dek=self.note_wrapped_dek, cipher=self.note_cipher)


class GmailConnection(Base):
    """The writer's Gmail, connected with the gmail.send scope only. The refresh token is only stored encrypted."""

    __tablename__ = "gmail_connections"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    email: Mapped[str] = mapped_column(Text)  # the Gmail address notes are sent from (and tests sent to)
    # The refresh token, sealed like a Stripe key (app/crypto.py).
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    cipher: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)  # ok | revoked (Google refused the token: reconnect)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    last_sent_at: Mapped[datetime | None]

    @property
    def aad(self) -> str:
        return f"gmail_connection:{self.user_id}"

    @property
    def sealed(self) -> Sealed:
        return Sealed(ciphertext=self.ciphertext, wrapped_dek=self.wrapped_dek, cipher=self.cipher)


class SubstackList(Base):
    """One publication's free subscribers, as of its latest Substack export (app/substack_list.py). One per
    publication the writer runs; each upload replaces that publication's last."""

    __tablename__ = "substack_lists"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    publication: Mapped[str] = mapped_column(Text, primary_key=True)  # its subdomain on substack.com
    exported_at: Mapped[datetime]  # from the export's filename; the upload time when it doesn't say
    uploaded_at: Mapped[datetime]
    free_count: Mapped[int]
    # The data key that encrypts the subscribers' emails and names, sealed like a Stripe key (app/crypto.py).
    key_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    key_wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    key_cipher: Mapped[str] = mapped_column(Text)

    @property
    def aad(self) -> str:
        return f"substack_list:{self.user_id}:{self.publication}"

    @property
    def sealed_key(self) -> Sealed:
        return Sealed(ciphertext=self.key_ciphertext, wrapped_dek=self.key_wrapped_dek, cipher=self.key_cipher)


class SubstackSubscriber(Base):
    """One free subscriber from the writer's Substack export. Email and first name are encrypted under the
    list's data key; the engagement counts, which identify nobody, are kept plain for ranking."""

    __tablename__ = "substack_subscribers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "publication"], ["substack_lists.user_id", "substack_lists.publication"], ondelete="CASCADE",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    publication: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(24), primary_key=True)  # app/customer_id.py
    email: Mapped[bytes] = mapped_column(LargeBinary)
    first_name: Mapped[bytes | None] = mapped_column(LargeBinary)
    started_at: Mapped[datetime]
    activity: Mapped[int] = mapped_column(default=0)
    emails_received_6mo: Mapped[int] = mapped_column(default=0)
    emails_opened_6mo: Mapped[int] = mapped_column(default=0)
    days_active_30d: Mapped[int] = mapped_column(default=0)
    post_views_30d: Mapped[int] = mapped_column(default=0)
    links_clicked: Mapped[int] = mapped_column(default=0)
    comments: Mapped[int] = mapped_column(default=0)
    shares: Mapped[int] = mapped_column(default=0)


def substack_subscriber_aad(user_id: uuid.UUID, publication: str, customer_id: str) -> bytes:
    return f"substack_subscriber:{user_id}:{publication}:{customer_id}".encode()
