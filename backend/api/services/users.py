"""User-related domain service logic."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.models import User


async def get_user_by_username_service(
    session: AsyncSession,
    *,
    username: str,
) -> Optional[User]:
    """Retrieve a user by username."""
    query = select(User).where(User.username == username)
    result = await session.execute(query)
    return result.scalars().first()
