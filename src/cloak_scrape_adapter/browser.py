from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from cloak_scrape_adapter.models import ScrapeRequest, Settings
from cloak_scrape_adapter.security import TargetGuard, UnsafeTargetError, redact_url

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScrapeResult:
    content: str
    page_status_code: int | None
    content_type: str | None
    page_error: str | None = None


@dataclass(slots=True)
class _SecurityState:
    blocked_navigation_url: str | None = None


def _http_error(status: int | None) -> str | None:
    if status is None or status == HTTPStatus.OK:
        return None
    try:
        phrase = HTTPStatus(status).phrase
    except ValueError:
        phrase = "Remote server error"
    return f"HTTP {status}: {phrase}"


def _header_value(headers: dict[str, str], name: str) -> str | None:
    expected = name.lower()
    return next(
        (value for key, value in headers.items() if key.lower() == expected),
        None,
    )


def _cookies_from_header(value: str, url: str) -> list[dict[str, str]]:
    cookies: list[dict[str, str]] = []
    for pair in value.split(";"):
        name, separator, cookie_value = pair.strip().partition("=")
        if not separator or not name:
            continue
        cookies.append({"name": name, "value": cookie_value, "url": url})
    return cookies


async def _close_quietly(resource: Any) -> None:
    if resource is None:
        return
    try:
        await resource.close()
    except Exception:
        logger.warning("browser resource cleanup failed: %s", type(resource).__name__)


class BrowserManager:
    def __init__(
        self,
        settings: Settings,
        *,
        guard: TargetGuard | None = None,
        browser_factory: Any | None = None,
    ) -> None:
        self.settings = settings
        self.guard = guard or TargetGuard(
            allow_local=settings.allow_local_webhooks,
        )
        self._browser_factory = browser_factory
        self._browser: Any | None = None
        self._launch_lock = asyncio.Lock()
        self._active_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_pages)
        self._active_pages = 0
        self._has_launched = False

    @property
    def active_pages(self) -> int:
        return self._active_pages

    @property
    def max_concurrent_pages(self) -> int:
        return self.settings.max_concurrent_pages

    def _is_connected(self) -> bool:
        if self._browser is None:
            return False
        try:
            return bool(self._browser.is_connected())
        except Exception:
            return False

    async def _default_browser_factory(self, **kwargs: Any) -> Any:
        from cloakbrowser import launch_async

        return await launch_async(**kwargs)

    async def start(self) -> None:
        if self._is_connected():
            return
        async with self._launch_lock:
            if self._is_connected():
                return
            previous = self._browser
            self._browser = None
            await _close_quietly(previous)
            if self._has_launched:
                await asyncio.sleep(0.25)

            for name, value in self.settings.browser_environment().items():
                os.environ[name] = value

            factory = self._browser_factory or self._default_browser_factory
            self._browser = await factory(
                headless=self.settings.headless,
                proxy=self.settings.proxy(),
                license_key=self.settings.cloakbrowser_license_key,
                browser_version=self.settings.cloakbrowser_version,
            )
            self._has_launched = True

    async def close(self) -> None:
        async with self._launch_lock:
            browser = self._browser
            self._browser = None
            await _close_quietly(browser)

    @asynccontextmanager
    async def _page_slot(self):
        await self._semaphore.acquire()
        async with self._active_lock:
            self._active_pages += 1
        try:
            yield
        finally:
            async with self._active_lock:
                self._active_pages -= 1
            self._semaphore.release()

    async def health(self) -> None:
        await self.start()
        context = None
        page = None
        try:
            context = await self._browser.new_context(service_workers="block")
            page = await context.new_page()
        finally:
            await _close_quietly(page)
            await _close_quietly(context)

    async def _install_request_policy(
        self,
        context: Any,
        state: _SecurityState,
    ) -> None:
        async def handle(route: Any) -> None:
            request = route.request
            request_url = request.url
            try:
                await self.guard.assert_safe(request_url)
            except UnsafeTargetError:
                if request.is_navigation_request():
                    state.blocked_navigation_url = request_url
                logger.warning("blocked browser request to %s", redact_url(request_url))
                await route.abort(error_code="blockedbyclient")
                return

            if self.settings.block_media and request.resource_type in {"image", "media"}:
                await route.abort(error_code="blockedbyclient")
                return
            await route.continue_()

        await context.route("**/*", handle)

    async def scrape(self, request: ScrapeRequest) -> ScrapeResult:
        await self.guard.assert_safe(request.url)
        await self.start()

        context = None
        page = None
        state = _SecurityState()
        async with self._page_slot():
            try:
                context_options: dict[str, Any] = {
                    "ignore_https_errors": request.skip_tls_verification,
                    "service_workers": "block",
                }
                headers = request.headers or {}
                user_agent = _header_value(headers, "user-agent")
                if user_agent:
                    context_options["user_agent"] = user_agent

                context = await self._browser.new_context(**context_options)
                await self._install_request_policy(context, state)

                cookie_header = _header_value(headers, "cookie")
                if cookie_header:
                    cookies = _cookies_from_header(cookie_header, request.url)
                    if cookies:
                        await context.add_cookies(cookies)

                page = await context.new_page()
                extra_headers = {
                    name: value
                    for name, value in headers.items()
                    if name.lower() not in {"cookie", "user-agent"}
                }
                if extra_headers:
                    await page.set_extra_http_headers(extra_headers)

                logger.info("navigating to %s", redact_url(request.url))
                try:
                    response = await page.goto(
                        request.url,
                        wait_until="load",
                        timeout=request.timeout,
                    )
                except Exception as error:
                    if state.blocked_navigation_url is not None:
                        raise UnsafeTargetError(
                            state.blocked_navigation_url,
                            "navigation to a private or non-global address is not allowed",
                        ) from error
                    raise

                if request.wait_after_load:
                    await page.wait_for_timeout(request.wait_after_load)
                if request.check_selector:
                    try:
                        await page.wait_for_selector(
                            request.check_selector,
                            timeout=request.timeout,
                        )
                    except Exception as error:
                        raise RuntimeError("Required selector not found") from error

                status: int | None = None
                content_type: str | None = None
                content = await page.content()
                if response is not None:
                    status = response.status
                    response_headers = await response.all_headers()
                    content_type = next(
                        (
                            value
                            for name, value in response_headers.items()
                            if name.lower() == "content-type"
                        ),
                        None,
                    )
                    normalized_type = (content_type or "").lower()
                    if "application/json" in normalized_type or "text/plain" in normalized_type:
                        content = (await response.body()).decode(
                            "utf-8",
                            errors="replace",
                        )

                return ScrapeResult(
                    content=content,
                    page_status_code=status,
                    content_type=content_type,
                    page_error=_http_error(status),
                )
            finally:
                await _close_quietly(page)
                await _close_quietly(context)
