from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from cloak_scrape_adapter.browser import BrowserManager
from cloak_scrape_adapter.models import (
    HealthResponse,
    ScrapeRequest,
    ScrapeResponse,
    Settings,
    UnhealthyResponse,
)
from cloak_scrape_adapter.security import InvalidTargetError, UnsafeTargetError

logger = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    manager: Any | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_manager = manager or BrowserManager(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await resolved_manager.start()
        try:
            yield
        finally:
            await resolved_manager.close()

    application = FastAPI(
        title="Cloak Scrape Adapter",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    application.state.browser_manager = resolved_manager

    @application.exception_handler(RequestValidationError)
    async def invalid_request(
        _: Request,
        __: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid request"},
        )

    @application.get("/health")
    async def health() -> JSONResponse:
        try:
            await resolved_manager.health()
        except Exception as error:
            logger.error("health check failed: %s", type(error).__name__)
            body = UnhealthyResponse().model_dump()
            return JSONResponse(status_code=503, content=body)

        body = HealthResponse(
            status="healthy",
            maxConcurrentPages=resolved_manager.max_concurrent_pages,
            activePages=resolved_manager.active_pages,
        ).model_dump()
        return JSONResponse(status_code=200, content=body)

    @application.post("/scrape")
    async def scrape(payload: ScrapeRequest) -> JSONResponse:
        try:
            result = await resolved_manager.scrape(payload)
        except InvalidTargetError:
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid URL"},
            )
        except UnsafeTargetError as error:
            body = ScrapeResponse(
                content="",
                pageStatusCode=403,
                pageError=str(error),
            ).model_dump(exclude_none=True)
            return JSONResponse(status_code=200, content=body)
        except Exception as error:
            logger.error("scrape failed: %s", type(error).__name__)
            return JSONResponse(
                status_code=500,
                content={"error": "An error occurred while fetching the page."},
            )

        body = ScrapeResponse(
            content=result.content,
            pageStatusCode=result.page_status_code,
            contentType=result.content_type,
            pageError=result.page_error,
        ).model_dump(exclude_none=True)
        return JSONResponse(status_code=200, content=body)

    return application


app = create_app()
