from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.admin_user import AdminUserRepository
from app.repositories.ledger import LedgerRepository
from app.services.admin_authorization import AdminAuthorizationService
from app.services.ledger import LedgerService


def build_ledger_service(session: AsyncSession) -> LedgerService:
    return LedgerService(
        session=session,
        repository=LedgerRepository(session),
        admin_authorization_service=AdminAuthorizationService(
            admin_user_repository=AdminUserRepository(session)
        ),
    )
