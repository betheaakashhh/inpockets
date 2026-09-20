from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db_session
from app.domain.admin import AdminRole, CUSTOMER_READ_ROLES
from app.models.admin_user import AdminUser
from app.models.user import User
from app.repositories.admin_user import AdminUserRepository


async def get_current_admin(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AdminUser:
    admin = await AdminUserRepository(session).get_by_user_id(current_user.id)

    if admin is None or not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    try:
        role = AdminRole(admin.role)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin role",
        ) from exc

    if role not in CUSTOMER_READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient admin permissions",
        )

    request.state.admin_user_id = admin.id
    return admin
