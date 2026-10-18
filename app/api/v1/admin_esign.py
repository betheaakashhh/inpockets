from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.esign import esign_http_error
from app.core.admin import get_current_admin
from app.db.session import get_db_session
from app.models.admin_user import AdminUser
from app.schemas.esign import AdminESignResponse
from app.services.esign_factory import build_esign_service

router = APIRouter()


@router.get("/{offer_id}/esign", response_model=AdminESignResponse)
async def admin_get_esign(
    offer_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_esign_service(session)
    try:
        tx, events = await service.get_for_admin(
            actor_user_id=admin.user_id, offer_id=offer_id
        )
    except Exception as exc:
        raise esign_http_error(exc) from exc
    return AdminESignResponse.from_tx(tx, events)
