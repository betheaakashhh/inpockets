"""Customer notification history and preferences. A customer only ever sees
their own, and never the variables, provider references or failure details."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.domain import notifications as dom
from app.models.user import User
from app.schemas.notifications import MyNotificationResponse, PreferenceItem, PreferenceUpdate
from app.services.notifications_factory import build_notification_service

router = APIRouter(dependencies=[Depends(limit_user("notifications"))])
WRITE = [Depends(limit_user("notifications-write", sensitive=True))]


def notification_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, dom.NotificationNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient admin permissions")
    if isinstance(exc, dom.NotificationConflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


@router.get("", response_model=list[MyNotificationResponse])
async def my_notifications(
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    rows = await build_notification_service(session).my_notifications(user_id=user.id, limit=limit)
    return [MyNotificationResponse.model_validate(r) for r in rows]


@router.get("/preferences", response_model=list[PreferenceItem])
async def my_preferences(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    return await build_notification_service(session).my_preferences(user_id=user.id)


@router.put("/preferences", response_model=list[PreferenceItem], dependencies=WRITE)
async def set_preference(
    payload: PreferenceUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_notification_service(session)
    try:
        await service.set_preference(
            user_id=user.id, category=payload.category, channel=payload.channel, enabled=payload.enabled
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise notification_http_error(exc) from exc
    return await service.my_preferences(user_id=user.id)
