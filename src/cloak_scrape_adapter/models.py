from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from os import environ
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_URL_LENGTH = 8_192
MAX_HEADER_COUNT = 128
MAX_HEADER_LENGTH = 16_384
MAX_SELECTOR_LENGTH = 2_048
MAX_TIMEOUT_MS = 300_000
MAX_WAIT_AFTER_LOAD_MS = 300_000


def _parse_bool(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _parse_int(
    name: str,
    value: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _optional(source: Mapping[str, str], name: str) -> str | None:
    value = source.get(name, "").strip()
    return value or None


@dataclass(frozen=True, slots=True)
class Settings:
    port: int = 3000
    max_concurrent_pages: int = 10
    block_media: bool = False
    allow_local_webhooks: bool = False
    headless: bool = True
    proxy_server: str | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None
    cloakbrowser_license_key: str | None = None
    cloakbrowser_cache_dir: Path = Path("/home/app/.cloakbrowser")
    cloakbrowser_version: str | None = None
    cloakbrowser_auto_update: bool = False

    @classmethod
    def from_env(cls, values: Mapping[str, str] | None = None) -> Settings:
        source = environ if values is None else values
        return cls(
            port=_parse_int(
                "PORT",
                source.get("PORT", "3000"),
                minimum=1,
                maximum=65_535,
            ),
            max_concurrent_pages=_parse_int(
                "MAX_CONCURRENT_PAGES",
                source.get("MAX_CONCURRENT_PAGES", "10"),
                minimum=1,
                maximum=1_000,
            ),
            block_media=_parse_bool(
                "BLOCK_MEDIA",
                source.get("BLOCK_MEDIA", "false"),
            ),
            allow_local_webhooks=_parse_bool(
                "ALLOW_LOCAL_WEBHOOKS",
                source.get("ALLOW_LOCAL_WEBHOOKS", "false"),
            ),
            headless=_parse_bool("HEADLESS", source.get("HEADLESS", "true")),
            proxy_server=_optional(source, "PROXY_SERVER"),
            proxy_username=_optional(source, "PROXY_USERNAME"),
            proxy_password=_optional(source, "PROXY_PASSWORD"),
            cloakbrowser_license_key=_optional(
                source,
                "CLOAKBROWSER_LICENSE_KEY",
            ),
            cloakbrowser_cache_dir=Path(
                source.get(
                    "CLOAKBROWSER_CACHE_DIR",
                    "/home/app/.cloakbrowser",
                ),
            ).expanduser(),
            cloakbrowser_version=_optional(source, "CLOAKBROWSER_VERSION"),
            cloakbrowser_auto_update=_parse_bool(
                "CLOAKBROWSER_AUTO_UPDATE",
                source.get("CLOAKBROWSER_AUTO_UPDATE", "false"),
            ),
        )

    def browser_environment(self) -> dict[str, str]:
        return {
            "CLOAKBROWSER_CACHE_DIR": str(self.cloakbrowser_cache_dir),
            "CLOAKBROWSER_AUTO_UPDATE": ("true" if self.cloakbrowser_auto_update else "false"),
        }

    def proxy(self) -> dict[str, str] | None:
        if self.proxy_server is None:
            return None
        proxy: dict[str, str] = {"server": self.proxy_server}
        if self.proxy_username is not None:
            proxy["username"] = self.proxy_username
        if self.proxy_password is not None:
            proxy["password"] = self.proxy_password
        return proxy


class ScrapeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=MAX_URL_LENGTH)
    wait_after_load: int = Field(
        default=0,
        ge=0,
        le=MAX_WAIT_AFTER_LOAD_MS,
    )
    timeout: int = Field(default=15_000, ge=1, le=MAX_TIMEOUT_MS)
    headers: dict[str, str] | None = None
    check_selector: str | None = Field(
        default=None,
        max_length=MAX_SELECTOR_LENGTH,
    )
    skip_tls_verification: bool = False

    @field_validator("headers")
    @classmethod
    def validate_headers(
        cls,
        headers: dict[str, str] | None,
    ) -> dict[str, str] | None:
        if headers is None:
            return None
        if len(headers) > MAX_HEADER_COUNT:
            raise ValueError("too many headers")
        for name, value in headers.items():
            if not name or len(name) > 256:
                raise ValueError("invalid header name")
            if "\r" in name or "\n" in name:
                raise ValueError("invalid header name")
            if len(value) > MAX_HEADER_LENGTH or "\r" in value or "\n" in value:
                raise ValueError("invalid header value")
        return headers

    @field_validator("check_selector")
    @classmethod
    def normalize_selector(cls, selector: str | None) -> str | None:
        if selector is None:
            return None
        stripped = selector.strip()
        return stripped or None


class HealthResponse(BaseModel):
    status: str
    maxConcurrentPages: int
    activePages: int


class UnhealthyResponse(BaseModel):
    status: str = "unhealthy"
    error: str = "Browser unavailable"


class ScrapeResponse(BaseModel):
    content: str
    pageStatusCode: int | None
    contentType: str | None = None
    pageError: str | None = None
