import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as DBPoolTimeout
from starlette.exceptions import HTTPException

from app.api.v1 import (
    analytics,
    articles,
    auth,
    classifications,
    contacts,
    logs,
    media,
    requests,
    subscriptions,
    users,
)
from app.core.config import Settings, get_settings
from app.core.errors import APIError
from app.core.limits import RateLimiter
from app.core.logging import configure_logging
from app.core.middleware import RequestProtection
from app.core.security import hash_password
from app.db.session import create_database
from app.integrations.nextjs import Revalidator
from app.schemas.common import Data, ErrorResponse
from app.services.media import media_cleanup_worker
from app.services.requests import SubmissionGuard
from app.services.scheduling import article_scheduler_worker


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    limiter = RateLimiter(config.limiter_max_keys)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        engine, factory = create_database(config)
        application.state.engine = engine
        application.state.session_factory = factory
        application.state.dummy_hash = await hash_password(secrets.token_urlsafe(32))
        try:
            async with httpx.AsyncClient(
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                timeout=httpx.Timeout(5, connect=2),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                application.state.revalidator = Revalidator(config, client)
                scheduler_task = None
                if config.article_scheduler_enabled:
                    scheduler_task = asyncio.create_task(
                        article_scheduler_worker(factory, config, application.state.revalidator)
                    )
                cleanup_task = None
                if (
                    config.cloudinary_cloud_name
                    and config.cloudinary_api_key
                    and config.cloudinary_api_secret
                ):
                    cleanup_task = asyncio.create_task(media_cleanup_worker(factory, config))
                try:
                    yield
                finally:
                    if scheduler_task is not None:
                        scheduler_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await scheduler_task
                    if cleanup_task is not None:
                        cleanup_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await cleanup_task
        finally:
            await engine.dispose()

    errors: dict[int | str, dict[str, Any]] = {
        code: {"model": ErrorResponse}
        for code in (401, 403, 404, 409, 413, 422, 429, 500, 503, 504)
    }
    application = FastAPI(
        title="Blog API",
        version="1.0.0",
        lifespan=lifespan,
        responses=errors,
        docs_url="/docs" if config.environment != "production" else None,
        redoc_url=None,
    )
    application.state.settings = config
    application.state.limiter = limiter
    application.state.submission_guard = SubmissionGuard(config.limiter_max_keys)
    application.add_middleware(RequestProtection, settings=config, limiter=limiter)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Protection"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    def error_response(request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            headers=exc.headers,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": getattr(request.state, "request_id", "unknown"),
                }
            },
        )

    @application.exception_handler(APIError)
    async def api_error(request: Request, exc: APIError) -> JSONResponse:
        return error_response(request, exc)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Never return Pydantic's input/context: those can contain passwords and private submissions.
        details = [
            {"location": [str(p) for p in error["loc"]], "type": error["type"]}
            for error in exc.errors()
        ]
        return error_response(
            request, APIError(422, "validation_error", "Invalid request", details)
        )

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return error_response(
            request,
            APIError(
                exc.status_code,
                "http_error",
                "Request could not be processed",
                headers=exc.headers,
            ),
        )

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        # Do not log exception strings, SQL, parameters or connection details.
        status = 503 if isinstance(exc, (DBAPIError, DBPoolTimeout)) else 500
        return error_response(
            request,
            APIError(status, "database_unavailable", "Database operation unavailable"),
        )

    for router in (
        auth.router,
        users.router,
        classifications.router,
        articles.router,
        analytics.router,
        requests.router,
        subscriptions.router,
        contacts.router,
        logs.router,
        media.router,
    ):
        application.include_router(router, prefix="/api/v1")

    def secured_openapi() -> dict[str, Any]:
        if application.openapi_schema:
            return application.openapi_schema
        schema = get_openapi(
            title=application.title, version=application.version, routes=application.routes
        )
        for path in schema.get("paths", {}).values():
            for operation in path.values():
                if not isinstance(operation, dict):
                    continue
                security = operation.get("security", [])
                if any(
                    "APIUser" in requirement or "APIKey" in requirement for requirement in security
                ):
                    operation["security"] = [{"APIUser": [], "APIKey": []}]
                    if any("HTTPBearer" in requirement for requirement in security):
                        operation["security"].append({"HTTPBearer": []})
        application.openapi_schema = schema
        return schema

    application.openapi = secured_openapi  # type: ignore[method-assign]

    @application.get("/health", tags=["Health"], response_model=Data[dict[str, str]])
    async def health() -> Data[dict[str, str]]:
        return Data(data={"status": "ok"})

    @application.get("/ready", tags=["Health"], response_model=Data[dict[str, str]])
    async def ready(request: Request) -> Data[dict[str, str]]:
        try:
            async with request.app.state.session_factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            raise APIError(503, "not_ready", "Database is unavailable") from None
        return Data(data={"status": "ready"})

    return application
