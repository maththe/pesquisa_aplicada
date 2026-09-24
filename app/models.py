from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.config import LogLevel, ServiceName


class HealthResponse(BaseModel):
    service: ServiceName
    status: Literal["ok"] = "ok"


class UserResponse(BaseModel):
    id: int
    name: str


class OrderResponse(BaseModel):
    id: int
    user: UserResponse
    item: str
    quantity: int
    status: Literal["confirmed"] = "confirmed"


class StructuredLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_id: UUID = Field(default_factory=uuid4)
    timestamp: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    service: ServiceName
    level: LogLevel
    event: str
    message: str
    request_id: str | None = None
    dependency: ServiceName | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    method: str | None = None
    path: str | None = None
    status_code: int | None = Field(default=None, ge=100, le=599)
    error_type: str | None = None

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)
