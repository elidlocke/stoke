from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings

# Repo-root .env, resolved from this file so it loads regardless of the working directory.
# Real environment variables take precedence over values in the file.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    # Creators' own keys are stored per user in Postgres (see app/credentials.py), not here.
    database_url: str = "postgresql+asyncpg://stoke:stoke@127.0.0.1:5432/stoke"

    # Encryption of stored Stripe keys (see app/crypto.py). "local": a 32-byte key from
    # STOKE_ENCRYPTION_KEY (64 hex characters). "aws_kms": envelope encryption under AWS_KMS_KEY_ID;
    # the master key never leaves KMS.
    key_cipher: Literal["local", "aws_kms"] = "local"
    stoke_encryption_key: SecretStr | None = None
    aws_kms_key_id: str | None = None

    # Auth0: the tenant domain (e.g. stoke.us.auth0.com) and the API identifier tokens are issued for.
    auth0_domain: str = ""
    auth0_audience: str = ""

    # Local development only: a Connect platform key whose accounts are added to every user's view.
    # Ignored unless DEV_MODE is true. STRIPE_API_KEY is accepted as the older name.
    # SecretStr keeps keys out of reprs, logs and tracebacks.
    dev_mode: bool = False
    stripe_platform_key: SecretStr | None = Field(
        None, validation_alias=AliasChoices("STRIPE_PLATFORM_KEY", "STRIPE_API_KEY")
    )
    stripe_account_ids: str = ""
    include_platform: bool = True

    # Key for the opaque customer ids in URLs (see app/customer_id.py). Required.
    customer_id_secret: SecretStr | None = None

    cors_origin: str = "https://localhost:5173"
    # Host headers the API answers to; anything else is rejected (guards against DNS rebinding).
    allowed_hosts: str = "127.0.0.1,localhost"
    cache_ttl_seconds: int = 300
    # Signing secret of the Connect webhook endpoint (scripts/register_webhook.py). Unset: no endpoint.
    stripe_webhook_secret: SecretStr | None = None
    # The Stripe App writers install to connect their accounts (app/stripe_app.py, docs/stripe-app-setup.md):
    # its OAuth install link, from the app's External test tab (later its public link), and the secret key of
    # the app's own Stripe account, in the same mode as the link. Unset: Stripe accounts can't be connected.
    stripe_app_install_url: str = ""
    stripe_app_secret_key: SecretStr | None = None
    # Run imports and re-reads of changed objects in the background (app/sync.py). Off in tests.
    sync_worker: bool = True
    # Google OAuth client (a "Web application" client in Google Cloud) for sending notes from the
    # writer's Gmail with the gmail.send scope (app/gmail.py). Unset: Gmail can't be connected.
    google_client_id: str = ""
    google_client_secret: SecretStr | None = None
    # The built frontend (frontend/dist), served by the API in the production image. Unset in
    # development, where the Vite dev server serves it.
    static_dir: Path | None = None

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, url: str) -> str:
        # Hosts like Render hand out postgres:// or postgresql:// URLs; the app connects via asyncpg.
        for scheme in ("postgres://", "postgresql://"):
            if url.startswith(scheme):
                return "postgresql+asyncpg://" + url.removeprefix(scheme)
        return url

    @property
    def account_allowlist(self) -> list[str]:
        return [a.strip() for a in self.stripe_account_ids.split(",") if a.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def gmail_redirect_uri(self) -> str:
        """Where Google sends the writer back after consent: the API's callback, at the frontend's origin (the
        Vite dev server proxies /api; in production they share one). Register it on the OAuth client exactly
        as written here."""
        return self.cors_origin.rstrip("/") + "/api/gmail/callback"

    @property
    def stripe_app_redirect_uri(self) -> str:
        """Where Stripe sends the writer back after installing the app, like gmail_redirect_uri. Listed in the app
        manifest's allowed_redirect_uris (stripe-app/stripe-app.json)."""
        return self.cors_origin.rstrip("/") + "/api/stripe/callback"

    @property
    def dev_platform_key(self) -> str | None:
        if self.dev_mode and self.stripe_platform_key is not None:
            return self.stripe_platform_key.get_secret_value() or None
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
