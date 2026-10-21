from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import field_validator

from app.schemas.common import Output


class LogResponse(Output):
    id: UUID
    user_id: UUID | None
    action: str
    entity_type: str
    entity_id: UUID | None
    details: dict[str, Any] | None
    ip_address: str | None
    created_at: datetime

    @field_validator("ip_address", mode="before")
    @classmethod
    def stringify_ip(cls, value: Any) -> str | None:
        return str(value) if value is not None else None
