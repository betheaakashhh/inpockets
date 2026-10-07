from uuid import uuid4

import pytest

from app.domain.admin import AdminRole
from app.models.admin_user import AdminUser
from app.services.audit_log import AuditLogService


@pytest.mark.asyncio
async def test_record_admin_action_uses_database_role(
    db_session,
    user,
    admin_user,
):
    service = AuditLogService(
        audit_log_repository=__import__(
            "app.repositories.audit_log",
            fromlist=["AuditLogRepository"],
        ).AuditLogRepository(db_session),
        admin_user_repository=__import__(
            "app.repositories.admin_user",
            fromlist=["AdminUserRepository"],
        ).AdminUserRepository(db_session),
    )

    audit = await service.record_admin_action(
        actor_user_id=user.id,
        action="UNDERWRITING_REVIEW_STARTED",
        entity_type="underwriting_review_case",
        entity_id=str(uuid4()),
        reason="Manual review started",
        old_value={"status": "ASSIGNED"},
        new_value={"status": "IN_REVIEW"},
    )

    assert audit.actor_admin_user_id == admin_user.id
    assert audit.actor_role == AdminRole.UNDERWRITER.value
    assert audit.action == "UNDERWRITING_REVIEW_STARTED"
    assert audit.old_value == {"status": "ASSIGNED"}
    assert audit.new_value == {"status": "IN_REVIEW"}


@pytest.mark.asyncio
async def test_record_admin_action_rejects_non_admin(
    db_session,
    user,
):
    from app.repositories.admin_user import AdminUserRepository
    from app.repositories.audit_log import AuditLogRepository

    service = AuditLogService(
        audit_log_repository=AuditLogRepository(db_session),
        admin_user_repository=AdminUserRepository(db_session),
    )

    with pytest.raises(PermissionError, match="not an admin"):
        await service.record_admin_action(
            actor_user_id=user.id,
            action="TEST",
            entity_type="test",
            entity_id=str(uuid4()),
        )


@pytest.mark.asyncio
async def test_record_admin_action_rejects_inactive_admin(
    db_session,
    user,
    admin_user,
):
    from app.repositories.admin_user import AdminUserRepository
    from app.repositories.audit_log import AuditLogRepository

    admin_user.is_active = False
    await db_session.flush()

    service = AuditLogService(
        audit_log_repository=AuditLogRepository(db_session),
        admin_user_repository=AdminUserRepository(db_session),
    )

    with pytest.raises(PermissionError, match="inactive"):
        await service.record_admin_action(
            actor_user_id=user.id,
            action="TEST",
            entity_type="test",
            entity_id=str(uuid4()),
        )