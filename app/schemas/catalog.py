from typing import Literal

from pydantic import BaseModel

from app.config import ServiceName


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
