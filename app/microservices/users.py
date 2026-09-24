from fastapi import APIRouter, HTTPException

from app.models import UserResponse

router = APIRouter()


@router.get("/users/{user_id}")
async def get_user(user_id: int) -> UserResponse:
    if user_id != 1:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return UserResponse(id=1, name="Usuário de demonstração")
