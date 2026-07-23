# backend/api/router.py — auth routes only
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import (
    auth_backend,
    current_active_user,
    fastapi_users,
)
from backend.api.models import User
from backend.api.schemas import (
    TokenPayload,
    UserCreate,
    UserRead,
    UserUpdate,
)
from backend.api.service import validate_jwt_token
from backend.database import get_async_session

router = APIRouter()

router.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/jwt",
    tags=["auth"],
)
router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="",
    tags=["auth"],
)
router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)


@router.post("/validate-token", tags=["auth"])
async def validate_token(payload: TokenPayload):
    """Validate a JWT token and return user info if valid"""
    return validate_jwt_token(payload.token)


@router.get("/users/{username}", response_model=UserRead, tags=["users"])
async def get_user_by_username(
    username: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Get a user by username"""
    query = select(User).where(User.username == username)
    result = await session.execute(query)
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user

