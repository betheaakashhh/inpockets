import asyncio
import selectors
import sys
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.domain.admin import AdminRole
from app.models.user import User
from app.models.admin_user import AdminUser


async def seed_super_admin(phone_number: str) -> None:
    async with AsyncSessionLocal() as session:
        # 1. Find or create the base User in `users`
        result = await session.execute(
            select(User).where(User.phone_number == phone_number)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                phone_number=phone_number,
                is_active=True,
            )
            session.add(user)
            await session.flush()
            print(f"Created base User: id={user.id}, phone={phone_number}")
        else:
            print(f"Found existing User: id={user.id}, phone={phone_number}")

        # 2. Find or create the linked AdminUser in `admin_users`
        admin_result = await session.execute(
            select(AdminUser).where(AdminUser.user_id == user.id)
        )
        admin = admin_result.scalar_one_or_none()

        if admin is None:
            admin = AdminUser(
                user_id=user.id,
                role=AdminRole.SUPER_ADMIN.value,
                is_active=True,
            )
            session.add(admin)
            await session.commit()
            print(f"Created SUPER_ADMIN: admin_id={admin.id} for user_id={user.id}")
        else:
            admin.role = AdminRole.SUPER_ADMIN.value
            admin.is_active = True
            await session.commit()
            print(f"Updated existing AdminUser: admin_id={admin.id} to SUPER_ADMIN")


if __name__ == "__main__":
    target_phone = sys.argv[1] if len(sys.argv) > 1 else "+919999999999"

    if sys.platform == "win32":
        asyncio.run(
            seed_super_admin(target_phone),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    else:
        asyncio.run(seed_super_admin(target_phone))