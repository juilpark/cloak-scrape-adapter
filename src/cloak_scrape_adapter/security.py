from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import SplitResult, urlsplit, urlunsplit

Resolver = Callable[[str, int], Awaitable[Iterable[str]]]


class UnsafeTargetError(ValueError):
    def __init__(self, url: str, reason: str) -> None:
        self.url = redact_url(url)
        self.reason = reason
        super().__init__(f'Blocked target URL "{self.url}": {reason}')


class InvalidTargetError(UnsafeTargetError):
    """A malformed or unsupported initial target URL."""


async def _system_resolver(hostname: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(
        hostname,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    )
    return list({record[4][0] for record in records})


def redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        if hostname is None:
            return value
        host = f"[{hostname}]" if ":" in hostname else hostname
        try:
            port = parsed.port
        except ValueError:
            port = None
        netloc = f"{host}:{port}" if port is not None else host
        return urlunsplit(
            SplitResult(
                parsed.scheme,
                netloc,
                parsed.path,
                "",
                "",
            ),
        )
    except (TypeError, ValueError):
        return "<invalid-url>"


def _normalize_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address):
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _is_blocked_address(value: str) -> bool:
    try:
        address = _normalize_ip(ipaddress.ip_address(value))
    except ValueError:
        return True
    return not address.is_global


def _literal_ip(hostname: str):
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        return None


def _parse_http_url(value: str) -> tuple[str, int]:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError) as error:
        raise InvalidTargetError(value, "URL is invalid") from error

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        protocol = f"{scheme}:" if scheme else "<missing>"
        raise InvalidTargetError(value, f'unsupported protocol "{protocol}"')
    if hostname is None or not hostname.rstrip("."):
        raise InvalidTargetError(value, "hostname is missing")

    hostname = hostname.rstrip(".")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise InvalidTargetError(value, "hostname is invalid") from error
    return hostname, port or (443 if scheme == "https" else 80)


class TargetGuard:
    """Default-deny URL and DNS validator.

    DNS is validated again for every routed browser request. This reduces, but
    cannot entirely remove, the DNS rebinding race between validation and the
    browser's own connection.
    """

    def __init__(
        self,
        *,
        allow_local: bool = False,
        resolver: Resolver | None = None,
    ) -> None:
        self.allow_local = allow_local
        self._resolver = resolver or _system_resolver

    async def assert_safe(self, url: str) -> None:
        hostname, port = _parse_http_url(url)
        if self.allow_local:
            return

        literal = _literal_ip(hostname)
        if literal is not None:
            addresses = [str(literal)]
        else:
            try:
                addresses = list(await self._resolver(hostname, port))
            except (TimeoutError, OSError) as error:
                raise UnsafeTargetError(
                    url,
                    "hostname could not be resolved safely",
                ) from error

        if not addresses:
            raise UnsafeTargetError(url, "hostname returned no addresses")
        if any(_is_blocked_address(address) for address in addresses):
            raise UnsafeTargetError(
                url,
                "hostname resolves to a private or non-global address",
            )
