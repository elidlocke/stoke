from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings

# Repo-root .env, resolved from this file so it loads regardless of the working directory.
# Real environment variables take precedence over values in the file.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    # Platform mode: a Connect platform's key; connected accounts are read via the Stripe-Account header.
    # STRIPE_API_KEY is accepted as the older name.
    # SecretStr keeps keys out of reprs, logs and tracebacks.
    stripe_platform_key: SecretStr | None = Field(
        None, validation_alias=AliasChoices("STRIPE_PLATFORM_KEY", "STRIPE_API_KEY")
    )
    stripe_account_ids: str = ""
    include_platform: bool = True

    # Creator mode: comma-separated keys, each scoped to one creator's own Stripe account.
    stripe_account_keys: SecretStr = SecretStr("")

    # Currency everything is converted to. Default: the platform's payout currency, else the first account's.
    reporting_currency: str | None = None

    # Key for the opaque customer ids in URLs. Empty: a random key is generated on first run and
    # kept in customer_id_secret_file, so ids survive API key rotation and accounts coming and going.
    customer_id_secret: SecretStr | None = None
    customer_id_secret_file: Path = ENV_FILE.parent / ".customer_id_secret"

    cors_origin: str = "http://localhost:5173"
    cache_ttl_seconds: int = 300

    @property
    def account_allowlist(self) -> list[str]:
        return [a.strip() for a in self.stripe_account_ids.split(",") if a.strip()]

    @property
    def account_keys(self) -> list[str]:
        return [k.strip() for k in self.stripe_account_keys.get_secret_value().split(",") if k.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
