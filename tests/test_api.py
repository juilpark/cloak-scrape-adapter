from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cloak_scrape_adapter.app import create_app
from cloak_scrape_adapter.browser import BrowserManager, ScrapeResult
from cloak_scrape_adapter.models import ScrapeRequest, Settings
from cloak_scrape_adapter.security import (
    InvalidTargetError,
    TargetGuard,
    UnsafeTargetError,
)


class FakeManager:
    max_concurrent_pages = 3
    active_pages = 0

    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.result = ScrapeResult(
            content="<html>ok</html>",
            page_status_code=200,
            content_type="text/html",
        )
        self.error: Exception | None = None
        self.last_request: ScrapeRequest | None = None

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def health(self) -> None:
        if self.error is not None:
            raise self.error

    async def scrape(self, request: ScrapeRequest) -> ScrapeResult:
        self.last_request = request
        if self.error is not None:
            raise self.error
        return self.result


def test_health_checks_browser_and_lifespan() -> None:
    manager = FakeManager()
    with TestClient(create_app(manager=manager)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "healthy",
            "maxConcurrentPages": 3,
            "activePages": 0,
        }
        assert manager.started is True
    assert manager.closed is True


def test_unhealthy_response_does_not_leak_exception_message() -> None:
    manager = FakeManager()
    manager.error = RuntimeError("proxy password is swordfish")
    with TestClient(create_app(manager=manager)) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unhealthy",
        "error": "Browser unavailable",
    }
    assert "swordfish" not in response.text


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        ('{"ok":true}', "application/json"),
        ("plain text", "text/plain; charset=utf-8"),
        ("<html>ok</html>", "text/html"),
    ],
)
def test_scrape_preserves_content_and_contract(
    content: str,
    content_type: str,
) -> None:
    manager = FakeManager()
    manager.result = ScrapeResult(
        content=content,
        page_status_code=200,
        content_type=content_type,
    )
    with TestClient(create_app(manager=manager)) as client:
        response = client.post(
            "/scrape",
            json={
                "url": "https://example.com",
                "wait_after_load": 10,
                "timeout": 20_000,
                "headers": {"Accept-Language": "ko-KR"},
                "check_selector": "h1",
                "skip_tls_verification": True,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "content": content,
        "pageStatusCode": 200,
        "contentType": content_type,
    }
    assert manager.last_request is not None
    assert manager.last_request.wait_after_load == 10


def test_remote_error_stays_in_successful_http_response() -> None:
    manager = FakeManager()
    manager.result = ScrapeResult(
        content="<html>missing</html>",
        page_status_code=404,
        content_type="text/html",
        page_error="HTTP 404: Not Found",
    )
    with TestClient(create_app(manager=manager)) as client:
        response = client.post("/scrape", json={"url": "https://example.com/missing"})

    assert response.status_code == 200
    assert response.json()["pageStatusCode"] == 404
    assert response.json()["pageError"] == "HTTP 404: Not Found"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"url": "https://example.com", "timeout": -1},
        {"url": "https://example.com", "unknown": True},
    ],
)
def test_invalid_request_returns_400(payload: dict[str, object]) -> None:
    with TestClient(create_app(manager=FakeManager())) as client:
        response = client.post("/scrape", json=payload)
    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request"}


def test_blocked_target_is_reported_as_page_status_403() -> None:
    manager = FakeManager()
    manager.error = UnsafeTargetError(
        "http://user:secret@127.0.0.1/admin",
        "private address",
    )
    with TestClient(create_app(manager=manager)) as client:
        response = client.post(
            "/scrape",
            json={"url": "http://127.0.0.1/admin"},
        )

    assert response.status_code == 200
    assert response.json()["pageStatusCode"] == 403
    assert response.json()["content"] == ""
    assert "secret" not in response.text


def test_invalid_target_returns_400() -> None:
    manager = FakeManager()
    manager.error = InvalidTargetError("not a URL", "URL is invalid")
    with TestClient(create_app(manager=manager)) as client:
        response = client.post("/scrape", json={"url": "not a URL"})

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid URL"}


def test_internal_error_is_generic() -> None:
    manager = FakeManager()
    manager.error = RuntimeError("CLOAKBROWSER_LICENSE_KEY=secret")
    with TestClient(create_app(manager=manager)) as client:
        response = client.post(
            "/scrape",
            json={"url": "https://example.com"},
        )
    assert response.status_code == 500
    assert response.json() == {
        "error": "An error occurred while fetching the page.",
    }
    assert "secret" not in response.text


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        content_type: str = "text/html",
        body: bytes = b"",
    ) -> None:
        self.status = status
        self._content_type = content_type
        self._body = body

    async def all_headers(self) -> dict[str, str]:
        return {"content-type": self._content_type}

    async def body(self) -> bytes:
        return self._body


class FakePage:
    def __init__(self, response: FakeResponse | None = None) -> None:
        self.response = response or FakeResponse()
        self.goto_error: Exception | None = None
        self.closed = False
        self.extra_headers: dict[str, str] = {}
        self.waited_ms: int | None = None
        self.waited_selector: tuple[str, int] | None = None

    async def goto(self, *_: Any, **__: Any) -> FakeResponse:
        if self.goto_error is not None:
            raise self.goto_error
        return self.response

    async def content(self) -> str:
        return "<html>rendered</html>"

    async def set_extra_http_headers(self, headers: dict[str, str]) -> None:
        self.extra_headers = headers

    async def wait_for_timeout(self, milliseconds: int) -> None:
        self.waited_ms = milliseconds

    async def wait_for_selector(self, selector: str, **options: Any) -> None:
        self.waited_selector = (selector, options["timeout"])

    async def close(self) -> None:
        self.closed = True


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.closed = False
        self.cookies: list[dict[str, str]] = []
        self.route_handler: Callable[..., Any] | None = None

    async def route(self, _: str, handler: Callable[..., Any]) -> None:
        self.route_handler = handler

    async def add_cookies(self, cookies: list[dict[str, str]]) -> None:
        self.cookies = cookies

    async def new_page(self) -> FakePage:
        return self.page

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.contexts: list[FakeContext] = []
        self.context_options: list[dict[str, Any]] = []
        self.connected = True
        self.closed = False

    def is_connected(self) -> bool:
        return self.connected

    async def new_context(self, **options: Any) -> FakeContext:
        self.context_options.append(options)
        context = FakeContext(self.page)
        self.contexts.append(context)
        return context

    async def close(self) -> None:
        self.closed = True
        self.connected = False


async def _allow_local_manager(
    page: FakePage,
    *,
    max_pages: int = 1,
) -> tuple[BrowserManager, FakeBrowser, dict[str, Any]]:
    browser = FakeBrowser(page)
    launch_options: dict[str, Any] = {}

    async def factory(**options: Any) -> FakeBrowser:
        launch_options.update(options)
        return browser

    manager = BrowserManager(
        Settings(max_concurrent_pages=max_pages, allow_local_webhooks=True),
        guard=TargetGuard(allow_local=True),
        browser_factory=factory,
    )
    await manager.start()
    return manager, browser, launch_options


async def test_browser_manager_preserves_fingerprint_defaults_and_headers() -> None:
    page = FakePage()
    manager, browser, launch_options = await _allow_local_manager(page)
    request = ScrapeRequest(
        url="http://127.0.0.1/test",
        headers={
            "User-Agent": "explicit-agent",
            "Cookie": "session=abc; theme=dark",
            "Accept-Language": "ko-KR",
        },
        wait_after_load=25,
        check_selector="#content",
    )

    result = await manager.scrape(request)
    context = browser.contexts[-1]

    assert launch_options["headless"] is True
    assert browser.context_options[-1]["user_agent"] == "explicit-agent"
    assert "viewport" not in browser.context_options[-1]
    assert context.cookies == [
        {"name": "session", "value": "abc", "url": request.url},
        {"name": "theme", "value": "dark", "url": request.url},
    ]
    assert page.extra_headers == {"Accept-Language": "ko-KR"}
    assert page.waited_ms == 25
    assert page.waited_selector == ("#content", 15_000)
    assert result.content == "<html>rendered</html>"
    assert page.closed is True
    assert context.closed is True
    assert manager.active_pages == 0
    await manager.close()


@pytest.mark.parametrize(
    ("content_type", "body", "expected"),
    [
        ("application/json; charset=utf-8", b'{"ok":true}', '{"ok":true}'),
        ("text/plain", b"plain", "plain"),
        ("text/html", b"ignored", "<html>rendered</html>"),
    ],
)
async def test_browser_manager_converts_response_body(
    content_type: str,
    body: bytes,
    expected: str,
) -> None:
    page = FakePage(FakeResponse(content_type=content_type, body=body))
    manager, _, _ = await _allow_local_manager(page)
    result = await manager.scrape(ScrapeRequest(url="http://127.0.0.1"))
    assert result.content == expected
    assert result.content_type == content_type
    await manager.close()


async def test_cleanup_and_semaphore_release_after_navigation_error() -> None:
    page = FakePage()
    page.goto_error = RuntimeError("navigation failed")
    manager, browser, _ = await _allow_local_manager(page, max_pages=1)

    with pytest.raises(RuntimeError):
        await manager.scrape(ScrapeRequest(url="http://127.0.0.1"))

    assert page.closed is True
    assert browser.contexts[-1].closed is True
    assert manager.active_pages == 0

    replacement = FakePage()
    browser.page = replacement
    result = await asyncio.wait_for(
        manager.scrape(ScrapeRequest(url="http://127.0.0.1")),
        timeout=1,
    )
    assert result.page_status_code == 200
    await manager.close()


class FakeRequest:
    def __init__(
        self,
        url: str,
        *,
        navigation: bool = False,
        resource_type: str = "script",
    ) -> None:
        self.url = url
        self.resource_type = resource_type
        self._navigation = navigation

    def is_navigation_request(self) -> bool:
        return self._navigation


class FakeRoute:
    def __init__(self, request: FakeRequest) -> None:
        self.request = request
        self.aborted = False
        self.continued = False

    async def abort(self, **_: Any) -> None:
        self.aborted = True

    async def continue_(self) -> None:
        self.continued = True


async def test_route_policy_blocks_private_subresource() -> None:
    async def resolver(_: str, __: int) -> list[str]:
        return ["8.8.8.8"]

    page = FakePage()
    browser = FakeBrowser(page)

    async def factory(**_: Any) -> FakeBrowser:
        return browser

    manager = BrowserManager(
        Settings(),
        guard=TargetGuard(resolver=resolver),
        browser_factory=factory,
    )
    await manager.start()
    await manager.scrape(ScrapeRequest(url="https://example.com"))
    handler = browser.contexts[-1].route_handler
    assert handler is not None

    route = FakeRoute(FakeRequest("http://127.0.0.1/internal"))
    await handler(route)
    assert route.aborted is True
    assert route.continued is False
    await manager.close()
