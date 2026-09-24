from fastapi import APIRouter

from app.microservices.client import ServiceRuntime
from app.models import OrderResponse, UserResponse


def build_router(runtime: ServiceRuntime) -> APIRouter:
    router = APIRouter()

    @router.get("/users/{user_id}")
    async def get_user(user_id: int) -> UserResponse:
        return await runtime.users().get(f"/users/{user_id}", UserResponse)

    @router.get("/orders/{order_id}")
    async def get_order(order_id: int) -> OrderResponse:
        return await runtime.orders().get(f"/orders/{order_id}", OrderResponse)

    return router
