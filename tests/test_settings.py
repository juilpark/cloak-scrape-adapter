from __future__ import annotations

import pytest
from pydantic import ValidationError

from cloak_scrape_adapter.models import ScrapeRequest, Settings


def test_settings_defaults() -> None:
    settings = Settings.from_env({})
    assert settings.port == 3000
    assert settings.max_concurrent_pages == 10
    assert settings.block_media is False
    assert settings.allow_local_webhooks is False
    assert settings.headless is True
    assert settings.cloakbrowser_auto_update is False
    assert str(settings.cloakbrowser_cache_dir) == "/home/app/.cloakbrowser"


def test_settings_parse_values_and_proxy() -> None:
    settings = Settings.from_env(
        {
            "PORT": "3100",
            "MAX_CONCURRENT_PAGES": "4",
            "BLOCK_MEDIA": "yes",
            "ALLOW_LOCAL_WEBHOOKS": "1",
            "HEADLESS": "off",
            "PROXY_SERVER": "http://proxy.example:8080",
            "PROXY_USERNAME": "user",
            "PROXY_PASSWORD": "secret",
            "CLOAKBROWSER_AUTO_UPDATE": "true",
        },
    )
    assert settings.port == 3100
    assert settings.max_concurrent_pages == 4
    assert settings.block_media is True
    assert settings.allow_local_webhooks is True
    assert settings.headless is False
    assert settings.proxy() == {
        "server": "http://proxy.example:8080",
        "username": "user",
        "password": "secret",
    }
    assert settings.browser_environment()["CLOAKBROWSER_AUTO_UPDATE"] == "true"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PORT", "0"),
        ("PORT", "65536"),
        ("MAX_CONCURRENT_PAGES", "0"),
        ("MAX_CONCURRENT_PAGES", "many"),
        ("BLOCK_MEDIA", "sometimes"),
    ],
)
def test_settings_reject_invalid_values(name: str, value: str) -> None:
    with pytest.raises(ValueError):
        Settings.from_env({name: value})


@pytest.mark.parametrize(
    "payload",
    [
        {"url": "https://example.com", "timeout": 0},
        {"url": "https://example.com", "timeout": 300_001},
        {"url": "https://example.com", "wait_after_load": -1},
        {"url": "https://example.com", "wait_after_load": 300_001},
        {
            "url": "https://example.com",
            "headers": {"X-Test": "line1\nline2"},
        },
    ],
)
def test_scrape_request_bounds(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ScrapeRequest.model_validate(payload)
