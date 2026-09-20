from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.admin_customer import AdminCustomerRepository
from app.repositories.audit_log import AuditLogRepository


class AdminCustomerService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.customer_repository = AdminCustomerRepository(session)
        self.audit_repository = AuditLogRepository(session)

    async def list_customers(self, *, page: int, page_size: int):
        offset = (page - 1) * page_size
        rows = await self.customer_repository.list_customers(offset=offset, limit=page_size)
        total = await self.customer_repository.count_customers()
        return rows, total

    async def get_customer(
        self,
        *,
        customer_id: UUID,
        admin_user_id: UUID,
        request_id: str | None,
        ip_address: str | None,
    ):
        row = await self.customer_repository.get_customer(customer_id)
        if row is None:
            return None

        await self.audit_repository.create(
            actor_admin_user_id=admin_user_id,
            action="ADMIN_VIEW_CUSTOMER",
            entity_type="CUSTOMER",
            entity_id=str(customer_id),
            request_id=request_id,
            ip_address=ip_address,
        )
        return row
