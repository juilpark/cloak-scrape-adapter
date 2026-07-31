from __future__ import annotations

import pytest

from cloak_scrape_adapter.security import (
    TargetGuard,
    UnsafeTargetError,
    redact_url,
)


async def public_resolver(_: str, __: int) -> list[str]:
    return ["8.8.8.8", "2606:4700:4700::1111"]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "data:text/plain,hello",
        "ftp://example.com/file",
        "ws://example.com/socket",
        "example.com",
        "not a url",
    ],
)
async def test_rejects_invalid_or_non_http_urls(url: str) -> None:
    guard = TargetGuard(resolver=public_resolver)
    with pytest.raises(UnsafeTargetError):
        await guard.assert_safe(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://10.0.0.1",
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0",
        "http://[::1]",
        "http://[fe80::1]",
        "http://[::ffff:127.0.0.1]",
        "http://192.0.2.10",
    ],
)
async def test_rejects_non_global_literal_addresses(url: str) -> None:
    guard = TargetGuard(resolver=public_resolver)
    with pytest.raises(UnsafeTargetError):
        await guard.assert_safe(url)


async def test_rejects_hostname_if_any_dns_answer_is_private() -> None:
    async def mixed_resolver(_: str, __: int) -> list[str]:
        return ["8.8.8.8", "10.10.10.10"]

    guard = TargetGuard(resolver=mixed_resolver)
    with pytest.raises(UnsafeTargetError):
        await guard.assert_safe("https://example.com")


async def test_rejects_empty_or_failed_dns_resolution() -> None:
    async def empty_resolver(_: str, __: int) -> list[str]:
        return []

    async def failed_resolver(_: str, __: int) -> list[str]:
        raise OSError("resolver unavailable")

    with pytest.raises(UnsafeTargetError):
        await TargetGuard(resolver=empty_resolver).assert_safe("https://example.com")
    with pytest.raises(UnsafeTargetError):
        await TargetGuard(resolver=failed_resolver).assert_safe("https://example.com")


async def test_rechecks_dns_on_every_request() -> None:
    calls = 0

    async def rebinding_resolver(_: str, __: int) -> list[str]:
        nonlocal calls
        calls += 1
        return ["8.8.8.8"] if calls == 1 else ["127.0.0.1"]

    guard = TargetGuard(resolver=rebinding_resolver)
    await guard.assert_safe("https://example.com")
    with pytest.raises(UnsafeTargetError):
        await guard.assert_safe("https://example.com/resource")


async def test_allows_global_addresses() -> None:
    guard = TargetGuard(resolver=public_resolver)
    await guard.assert_safe("https://example.com/path")
    await guard.assert_safe("https://8.8.8.8/")
    await guard.assert_safe("https://[2606:4700:4700::1111]/")


async def test_allow_local_still_enforces_http_protocol() -> None:
    guard = TargetGuard(allow_local=True)
    await guard.assert_safe("http://127.0.0.1:8080/test")
    with pytest.raises(UnsafeTargetError):
        await guard.assert_safe("file:///etc/passwd")


def test_redact_url_removes_userinfo_query_and_fragment() -> None:
    redacted = redact_url("https://user:secret@example.com:8443/path?q=1")
    assert redacted == "https://example.com:8443/path"
    assert "secret" not in redacted
    assert "q=1" not in redacted
