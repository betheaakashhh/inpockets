from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from app.models.audit_log import AuditLog


@pytest.mark.asyncio
async def test_audit_log_can_be_created(db_session):
    audit_log = AuditLog(
        action="UNDERWRITING_REVIEW_STARTED",
        entity_type="underwriting_review_case",
        entity_id=str(uuid4()),
        actor_role="UNDERWRITER",
        reason="Manual review started",
        old_value={"status": "ASSIGNED"},
        new_value={"status": "IN_REVIEW"},
    )

    db_session.add(audit_log)
    await db_session.flush()

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.id == audit_log.id)
    )
    saved = result.scalar_one()

    assert saved.action == "UNDERWRITING_REVIEW_STARTED"
    assert saved.actor_role == "UNDERWRITER"
    assert saved.old_value == {"status": "ASSIGNED"}
    assert saved.new_value == {"status": "IN_REVIEW"}


@pytest.mark.asyncio
async def test_audit_log_update_is_rejected(db_session):
    audit_log = AuditLog(
        action="TEST_ACTION",
        entity_type="test",
        entity_id=str(uuid4()),
    )

    db_session.add(audit_log)
    await db_session.flush()

    with pytest.raises(Exception, match="audit_logs is append-only"):
        await db_session.execute(
            update(AuditLog)
            .where(AuditLog.id == audit_log.id)
            .values(action="MUTATED")
        )
        await db_session.flush()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_audit_log_delete_is_rejected(db_session):
    audit_log = AuditLog(
        action="TEST_ACTION",
        entity_type="test",
        entity_id=str(uuid4()),
    )

    db_session.add(audit_log)
    await db_session.flush()

    with pytest.raises(Exception, match="audit_logs is append-only"):
        await db_session.execute(
            delete(AuditLog).where(AuditLog.id == audit_log.id)
        )
        await db_session.flush()

    await db_session.rollback()