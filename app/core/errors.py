from collections.abc import Mapping
from typing import Any


class APIError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers or {}
        super().__init__(message)


def not_found() -> APIError:
    return APIError(404, "not_found", "Resource not found")


def forbidden() -> APIError:
    return APIError(403, "forbidden", "Permission denied")
