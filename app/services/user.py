from app.models.user import User
from app.repositories.user import UserRepository


class UserStatusService:
    ALLOWED_STATUSES = {
        "active",
        "inactive",
        "blocked",
    }

    def __init__(self, repository: UserRepository):
        self.repository = repository

    async def update_status(
        self,
        user: User,
        *,
        new_status: str,
    ) -> User:
        if new_status not in self.ALLOWED_STATUSES:
            raise ValueError("Invalid user status")

        return await self.repository.update_status(
            user,
            status=new_status,
        )