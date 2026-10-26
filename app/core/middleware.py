import ipaddress
import logging
import time
from uuid import uuid4

import anyio
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.api_consumer import valid_api_consumer
from app.core.config import Settings
from app.core.errors import APIError
from app.core.limits import Limit, RateLimiter


def client_ip(scope: Scope) -> str:
    forwarded = scope.get("state", {}).get("verified_visitor_ip")
    if isinstance(forwarded, str):
        return forwarded
    client = scope.get("client")
    raw = client[0] if client else "127.0.0.1"
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return "127.0.0.1"


class RequestProtection:
    def __init__(self, app: ASGIApp, settings: Settings, limiter: RateLimiter) -> None:
        self.app, self.settings, self.limiter = app, settings, limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = False
        status = 500
        begin = time.monotonic()

        async def wrapped_send(message: Message) -> None:
            nonlocal started, status
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                message.setdefault("headers", []).extend(
                    [
                        (b"x-request-id", request_id.encode()),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    ]
                )
                credentialed = any(
                    name.lower() in {b"authorization", b"cookie", b"x-api-user", b"x-api-key"}
                    for name, _ in scope.get("headers", [])
                )
                if (
                    credentialed
                    or scope["path"].startswith(("/api/v1/admin", "/api/v1/auth", "/api/v1/users"))
                    or scope["method"] not in {"GET", "HEAD", "OPTIONS"}
                ):
                    # Authenticated taxonomy reads share public route paths.
                    # Override any route cache policy instead of adding a duplicate.
                    message["headers"] = [
                        (name, value)
                        for name, value in message["headers"]
                        if name.lower() != b"cache-control"
                    ]
                    message["headers"].append((b"cache-control", b"no-store"))
            await send(message)

        try:
            with anyio.fail_after(self.settings.request_timeout_seconds):
                if scope["method"] == "POST" and scope["path"].rstrip("/") in {
                    "/api/v1/article-requests",
                    "/api/v1/subscriptions",
                    "/api/v1/contact-messages",
                }:
                    headers = {
                        name.lower(): value.decode("latin-1")
                        for name, value in scope.get("headers", [])
                    }
                    if valid_api_consumer(
                        self.settings, headers.get(b"x-api-user"), headers.get(b"x-api-key")
                    ):
                        try:
                            scope["state"]["verified_visitor_ip"] = str(
                                ipaddress.ip_address(headers.get(b"x-visitor-ip", ""))
                            )
                        except ValueError:
                            pass
                    ip = client_ip(scope)
                    await self.limiter.check(
                        Limit(
                            f"submit:{scope['path'].rstrip('/')}:{ip}",
                            self.settings.submissions_per_ten_minutes,
                            600,
                        ),
                        Limit(
                            f"submit:{scope['path'].rstrip('/')}:{ip}",
                            self.settings.submissions_per_day,
                            86400,
                        ),
                    )
                if scope["method"] == "POST" and scope["path"].rstrip("/") == "/api/v1/auth/login":
                    await self.limiter.check(
                        Limit(f"login-ip:{client_ip(scope)}", self.settings.login_ip_per_minute, 60)
                    )
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > self.settings.max_body_bytes:
                        raise APIError(413, "body_too_large", "Request body is too large")
                    if not message.get("more_body", False):
                        break
                delivered = False

                async def replay() -> Message:
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                await self.app(scope, replay, wrapped_send)
        except TimeoutError:
            if not started:
                await self.error(
                    scope,
                    receive,
                    wrapped_send,
                    request_id,
                    APIError(504, "request_timeout", "Request timed out"),
                )
        except APIError as exc:
            if not started:
                await self.error(scope, receive, wrapped_send, request_id, exc)
        except Exception:
            logging.getLogger(__name__).error("request.unhandled_error request_id=%s", request_id)
            if not started:
                await self.error(
                    scope,
                    receive,
                    wrapped_send,
                    request_id,
                    APIError(500, "internal_error", "An internal error occurred"),
                )
        finally:
            logging.getLogger(__name__).info(
                "request.completed request_id=%s method=%s status=%s duration_ms=%s",
                request_id,
                scope["method"],
                status,
                round((time.monotonic() - begin) * 1000),
            )

    async def error(
        self, scope: Scope, receive: Receive, send: Send, request_id: str, exc: APIError
    ) -> None:
        await JSONResponse(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request_id,
                }
            },
            status_code=exc.status,
            headers=exc.headers,
        )(scope, receive, send)
