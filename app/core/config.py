from functools import lru_cache
from ipaddress import ip_network
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    environment: Literal["development", "test", "production"] = "development"
    database_url: str
    jwt_secret: SecretStr
    jwt_issuer: str = "blog-api"
    jwt_audience: str = "blog-clients"
    access_token_minutes: int = Field(default=30, ge=1, le=120)
    refresh_session_days: int = Field(default=7, ge=1, le=90)
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cors_origins: list[str] = []
    trusted_proxy_ips: list[str] = []
    db_pool_size: int = Field(default=10, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=20)
    db_pool_timeout: float = Field(default=5, gt=0)
    db_statement_timeout_ms: int = Field(default=10000, ge=100)
    db_lock_timeout_ms: int = Field(default=3000, ge=100)
    request_timeout_seconds: float = Field(default=30, ge=1)
    max_body_bytes: int = Field(default=2097152, ge=1024, le=8388608)
    limiter_max_keys: int = Field(default=10000, ge=100, le=100000)
    login_account_per_minute: int = Field(default=5, ge=1)
    login_ip_per_minute: int = Field(default=30, ge=1)
    mutations_per_minute: int = Field(default=60, ge=1)
    submissions_per_ten_minutes: int = Field(default=5, ge=1)
    submissions_per_day: int = Field(default=20, ge=1)
    nextjs_revalidation_url: str | None = None
    nextjs_revalidation_secret: SecretStr | None = None
    nextjs_revalidation_enabled: bool = False

    @model_validator(mode="after")
    def secure_settings(self) -> "Settings":
        if len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters")
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg")
        if "*" in self.cors_origins:
            raise ValueError("CORS origins must be explicitly allowlisted")
        for address in self.trusted_proxy_ips:
            try:
                ip_network(address, strict=False)
            except ValueError as exc:
                raise ValueError(
                    "Trusted proxies must be explicit IP addresses or networks"
                ) from exc
        for origin in self.cors_origins:
            url = urlsplit(origin)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path not in {"", "/"}
            ):
                raise ValueError("CORS origins must be absolute HTTP(S) origins")
            if self.environment == "production" and url.scheme != "https":
                raise ValueError("Production CORS origins must use HTTPS")
        if self.nextjs_revalidation_enabled:
            if not self.nextjs_revalidation_url or not self.nextjs_revalidation_secret:
                raise ValueError("Enabled revalidation requires URL and secret")
            url = urlsplit(self.nextjs_revalidation_url)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.fragment
                or url.query
            ):
                raise ValueError("Invalid revalidation URL")
            if self.environment == "production" and url.scheme != "https":
                raise ValueError("Production revalidation requires HTTPS")
            if len(self.nextjs_revalidation_secret.get_secret_value()) < 32:
                raise ValueError("Revalidation secret must contain at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
