"""Runtime settings, read from the environment names in .env.example."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The demo catalogue. The judge sandbox may never be pointed at one of these plans.
DEMO_PLAN_KEYS = frozenset({"pro", "pro_plus", "pro_eur"})

_OPTIONAL = (
    "stripe_secret_key",
    "notion_token",
    "notion_data_source_id",
    "airtable_pat",
    "airtable_base_id",
    "airtable_table",
    "slack_bot_token",
    "slack_app_token",
    "slack_approval_channel",
    "anthropic_api_key",
    "pq_signing_key",
    "pq_fault",
    "pq_operator_token",
    "pq_public_base_url",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_url: str = "postgresql://postgres@localhost:55432/pricequorum"
    stripe_secret_key: str | None = None
    notion_token: str | None = None
    notion_version: str = "2025-09-03"
    notion_data_source_id: str | None = None
    airtable_pat: str | None = None
    airtable_base_id: str | None = None
    airtable_table: str | None = None
    slack_bot_token: str | None = None
    slack_app_token: str | None = None
    slack_approval_channel: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"
    pq_signing_key: str | None = None
    pq_fault: str | None = None
    pq_allowed_origins: str = "http://localhost:3000"
    pq_operator_token: str | None = None
    pq_runs_per_minute: int = 10
    pq_approval_ttl_seconds: int = 1800
    pq_approval_poll_seconds: float = 1.0
    pq_rate_limit_wait_seconds: float = 30.0
    pq_max_step_attempts: int = 3
    pq_version: str = "0.1.0"
    pq_commit_sha: str = Field(
        default="unknown", validation_alias=AliasChoices("PQ_COMMIT_SHA", "RENDER_GIT_COMMIT", "pq_commit_sha")
    )
    # The URL this API answers on. The mounted MCP server calls the API through it.
    pq_public_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PQ_PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL", "pq_public_base_url"),
    )
    port: int = Field(default=8000, validation_alias=AliasChoices("PORT", "port"))
    pq_sandbox_plan_key: str = "judge_pro"
    pq_sandbox_runs_per_minute: int = 6
    pq_sandbox_cooldown_seconds: float = 10.0
    pq_sandbox_max_queue: int = 3
    pq_monitor_interval_seconds: float = 60.0

    @field_validator(*_OPTIONAL, mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("stripe_secret_key")
    @classmethod
    def _refuse_live_key(cls, value: str | None) -> str | None:
        if value and value.startswith(("sk_live_", "rk_live_")):
            raise ValueError("a live Stripe key was supplied; PriceQuorum runs in Stripe test mode only (sk_test_)")
        return value

    @field_validator("pq_sandbox_plan_key")
    @classmethod
    def _sandbox_plan_is_separate(cls, value: str) -> str:
        key = value.strip()
        if not re.fullmatch(r"[a-z0-9_]{1,64}", key):
            raise ValueError("PQ_SANDBOX_PLAN_KEY must be lowercase letters, digits and underscores")
        if key in DEMO_PLAN_KEYS:
            raise ValueError(f"the judge sandbox needs its own plan key; {key} is a demo plan")
        return key

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.pq_allowed_origins.split(",") if origin.strip()]

    @property
    def stripe_mode(self) -> str:
        """The contract reports "test"; without a test key the honest answer is "unconfigured"."""
        if self.stripe_secret_key and self.stripe_secret_key.startswith(("sk_test_", "rk_test_")):
            return "test"
        return "unconfigured"

    @property
    def public_base_url(self) -> str:
        if self.pq_public_base_url:
            return self.pq_public_base_url.rstrip("/")
        return f"http://127.0.0.1:{self.port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
