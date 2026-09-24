from fastapi import APIRouter, HTTPException

from app.microservices.client import ServiceRuntime
from app.models import OrderResponse, UserResponse


def build_router(runtime: ServiceRuntime) -> APIRouter:
    router = APIRouter()

    @router.get("/orders/{order_id}")
    async def get_order(order_id: int) -> OrderResponse:
        if order_id != 1:
            raise HTTPException(status_code=404, detail="Pedido não encontrado")
        user = await runtime.users().get("/users/1", UserResponse)
        return OrderResponse(id=1, user=user, item="Item de demonstração", quantity=1)

    return router
