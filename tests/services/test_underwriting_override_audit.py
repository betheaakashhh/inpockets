from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domain.admin import AdminRole
from app.models.admin_user import AdminUser
from app.models.loan_application import LoanApplication
from app.models.underwriting_review_case import UnderwritingReviewCase
from app.models.user import User
from app.services.underwriting_override import UnderwritingOverrideService


async def create_review_case(db_session, user):
    application = LoanApplication(
        user_id=user.id,
        application_number=f"TEST-{uuid4().hex[:12].upper()}",
        status="SUBMITTED",
        requested_amount=Decimal("10000.00"),
        requested_tenure_days=30,
    )
    db_session.add(application)
    await db_session.flush()

    case = UnderwritingReviewCase(
        loan_application_id=application.id,
        user_id=user.id,
        status="IN_REVIEW",
    )
    db_session.add(case)
    await db_session.flush()

    return case


async def create_override(
    *,
    service,
    admin_user,
    review_case,
):
    return await service.request_override(
        actor_user_id=admin_user.user_id,
        review_case_id=review_case.id,
        override_type="AMOUNT",
        original_value={"amount": "10000.00"},
        requested_value={"amount": "15000.00"},
        reason="Documented exception.",
    )


def audit_kwargs(audit_log_service):
    audit_log_service.record_admin_action.assert_awaited_once()
    return audit_log_service.record_admin_action.await_args.kwargs


@pytest.mark.asyncio
async def test_request_override_creates_requested_override(
    db_session,
    admin_user,
    user,
):
    admin_user.role = AdminRole.SENIOR_UNDERWRITER.value
    await db_session.flush()

    review_case = await create_review_case(db_session, user)

    audit_log_service = AsyncMock()
    service = UnderwritingOverrideService(
        session=db_session,
        audit_log_service=audit_log_service,
    )

    override = await create_override(
        service=service,
        admin_user=admin_user,
        review_case=review_case,
    )

    assert override.id is not None
    assert override.review_case_id == review_case.id
    assert override.requested_by_admin_user_id == admin_user.id
    assert override.override_type == "AMOUNT"
    assert override.status == "REQUESTED"

    audit = audit_kwargs(audit_log_service)
    assert audit["actor_user_id"] == admin_user.user_id
    assert audit["action"] == "UNDERWRITING_OVERRIDE_REQUESTED"
    assert audit["entity_type"] == "underwriting_override"
    assert audit["entity_id"] == str(override.id)
    assert audit["reason"] == "Documented exception."
    assert audit["old_value"]["status"] is None
    assert audit["new_value"]["status"] == "REQUESTED"
    assert audit["event_metadata"]["review_case_id"] == str(review_case.id)


@pytest.mark.asyncio
async def test_request_override_requires_reason(
    db_session,
    admin_user,
    user,
):
    admin_user.role = AdminRole.SENIOR_UNDERWRITER.value
    await db_session.flush()

    review_case = await create_review_case(db_session, user)
    audit_log_service = AsyncMock()
    service = UnderwritingOverrideService(
        session=db_session,
        audit_log_service=audit_log_service,
    )

    with pytest.raises(ValueError, match="override reason is required"):
        await service.request_override(
            actor_user_id=admin_user.user_id,
            review_case_id=review_case.id,
            override_type="AMOUNT",
            original_value={"amount": "10000.00"},
            requested_value={"amount": "15000.00"},
            reason="   ",
        )

    audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_override_requires_open_case(
    db_session,
    admin_user,
    user,
):
    admin_user.role = AdminRole.SENIOR_UNDERWRITER.value
    await db_session.flush()

    review_case = await create_review_case(db_session, user)
    review_case.status = "CLOSED"
    await db_session.flush()

    audit_log_service = AsyncMock()
    service = UnderwritingOverrideService(
        session=db_session,
        audit_log_service=audit_log_service,
    )

    with pytest.raises(
        ValueError,
        match="override can only be requested for an open review case",
    ):
        await create_override(
            service=service,
            admin_user=admin_user,
            review_case=review_case,
        )

    audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_override_requires_permission(
    db_session,
    admin_user,
    user,
):
    await db_session.flush()

    review_case = await create_review_case(db_session, user)
    audit_log_service = AsyncMock()
    service = UnderwritingOverrideService(
        session=db_session,
        audit_log_service=audit_log_service,
    )

    with pytest.raises(PermissionError):
        await service.request_override(
            actor_user_id=user.id,
            review_case_id=review_case.id,
            override_type="AMOUNT",
            original_value={"amount": "10000.00"},
            requested_value={"amount": "15000.00"},
            reason="Documented exception.",
        )

    audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_override_requires_values(
    db_session,
    admin_user,
    user,
):
    admin_user.role = AdminRole.SENIOR_UNDERWRITER.value
    await db_session.flush()

    review_case = await create_review_case(db_session, user)
    audit_log_service = AsyncMock()
    service = UnderwritingOverrideService(
        session=db_session,
        audit_log_service=audit_log_service,
    )

    with pytest.raises(ValueError, match="original_value is required"):
        await service.request_override(
            actor_user_id=admin_user.user_id,
            review_case_id=review_case.id,
            override_type="AMOUNT",
            original_value={},
            requested_value={"amount": "15000.00"},
            reason="Documented exception.",
        )

    with pytest.raises(ValueError, match="requested_value is required"):
        await service.request_override(
            actor_user_id=admin_user.user_id,
            review_case_id=review_case.id,
            override_type="AMOUNT",
            original_value={"amount": "10000.00"},
            requested_value={},
            reason="Documented exception.",
        )

    audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_override_requires_second_level_permission(
    db_session,
    admin_user,
    user,
):
    admin_user.role = AdminRole.SENIOR_UNDERWRITER.value
    await db_session.flush()

    review_case = await create_review_case(db_session, user)
    audit_log_service = AsyncMock()
    service = UnderwritingOverrideService(
        session=db_session,
        audit_log_service=audit_log_service,
    )

    override = await create_override(
        service=service,
        admin_user=admin_user,
        review_case=review_case,
    )

    # The request itself emitted an audit record; clear it before testing
    # the denied second-level approval.
    audit_log_service.reset_mock()

    admin_user.role = AdminRole.UNDERWRITER.value
    await db_session.flush()

    with pytest.raises(
        PermissionError,
        match="does not have permission LOAN_OVERRIDE_APPROVE",
    ):
        await service.approve_override(
            actor_user_id=admin_user.user_id,
            override_id=override.id,
        )

    audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_override_rejects_self_approval(
    db_session,
    admin_user,
    user,
):
    admin_user.role = AdminRole.SUPER_ADMIN.value
    await db_session.flush()

    review_case = await create_review_case(db_session, user)
    audit_log_service = AsyncMock()
    service = UnderwritingOverrideService(
        session=db_session,
        audit_log_service=audit_log_service,
    )

    override = await create_override(
        service=service,
        admin_user=admin_user,
        review_case=review_case,
    )
    audit_log_service.reset_mock()

    with pytest.raises(
        PermissionError,
        match="cannot approve their own override",
    ):
        await service.approve_override(
            actor_user_id=admin_user.user_id,
            override_id=override.id,
        )

    audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_override_records_second_level_approval(
    db_session,
    admin_user,
    user,
):
    admin_user.role = AdminRole.SUPER_ADMIN.value
    await db_session.flush()

    review_case = await create_review_case(db_session, user)
    audit_log_service = AsyncMock()
    service = UnderwritingOverrideService(
        session=db_session,
        audit_log_service=audit_log_service,
    )

    override = await create_override(
        service=service,
        admin_user=admin_user,
        review_case=review_case,
    )
    audit_log_service.reset_mock()

    second_user = User(
        phone_number=f"9{uuid4().int % 100_000_000:08d}",
    )
    db_session.add(second_user)
    await db_session.flush()

    second_admin = AdminUser(
        user_id=second_user.id,
        role=AdminRole.SUPER_ADMIN.value,
        is_active=True,
    )
    db_session.add(second_admin)
    await db_session.flush()

    approved = await service.approve_override(
        actor_user_id=second_admin.user_id,
        override_id=override.id,
    )

    assert approved.status == "APPROVED"
    assert approved.approved_by_admin_user_id == second_admin.id
    assert approved.approved_at is not None
    assert approved.requested_by_admin_user_id == admin_user.id

    audit = audit_kwargs(audit_log_service)
    assert audit["actor_user_id"] == second_admin.user_id
    assert audit["action"] == "UNDERWRITING_OVERRIDE_APPROVED"
    assert audit["entity_type"] == "underwriting_override"
    assert audit["entity_id"] == str(override.id)
    assert audit["reason"] == "Documented exception."
    assert audit["old_value"]["status"] == "REQUESTED"
    assert audit["new_value"]["status"] == "APPROVED"
    assert audit["event_metadata"]["review_case_id"] == str(review_case.id)


@pytest.mark.asyncio
async def test_reject_override_records_rejection(
    db_session,
    admin_user,
    user,
):
    admin_user.role = AdminRole.SUPER_ADMIN.value
    await db_session.flush()

    review_case = await create_review_case(db_session, user)
    audit_log_service = AsyncMock()
    service = UnderwritingOverrideService(
        session=db_session,
        audit_log_service=audit_log_service,
    )

    override = await create_override(
        service=service,
        admin_user=admin_user,
        review_case=review_case,
    )
    audit_log_service.reset_mock()

    second_user = User(
        phone_number=f"9{uuid4().int % 100_000_000:08d}",
    )
    db_session.add(second_user)
    await db_session.flush()

    second_admin = AdminUser(
        user_id=second_user.id,
        role=AdminRole.SUPER_ADMIN.value,
        is_active=True,
    )
    db_session.add(second_admin)
    await db_session.flush()

    rejected = await service.reject_override(
        actor_user_id=second_admin.user_id,
        override_id=override.id,
    )

    assert rejected.status == "REJECTED"
    assert rejected.rejected_at is not None
    assert rejected.approved_by_admin_user_id is None

    audit = audit_kwargs(audit_log_service)
    assert audit["actor_user_id"] == second_admin.user_id
    assert audit["action"] == "UNDERWRITING_OVERRIDE_REJECTED"
    assert audit["entity_type"] == "underwriting_override"
    assert audit["entity_id"] == str(override.id)
    assert audit["reason"] == "Documented exception."
    assert audit["old_value"]["status"] == "REQUESTED"
    assert audit["new_value"]["status"] == "REJECTED"
    assert audit["event_metadata"]["review_case_id"] == str(review_case.id)


@pytest.mark.asyncio
async def test_approve_override_rejects_already_approved(
    db_session,
    admin_user,
    user,
):
    admin_user.role = AdminRole.SUPER_ADMIN.value
    await db_session.flush()

    review_case = await create_review_case(db_session, user)
    audit_log_service = AsyncMock()
    service = UnderwritingOverrideService(
        session=db_session,
        audit_log_service=audit_log_service,
    )

    override = await create_override(
        service=service,
        admin_user=admin_user,
        review_case=review_case,
    )
    audit_log_service.reset_mock()

    second_user = User(
        phone_number=f"9{uuid4().int % 100_000_000:08d}",
    )
    db_session.add(second_user)
    await db_session.flush()

    second_admin = AdminUser(
        user_id=second_user.id,
        role=AdminRole.SUPER_ADMIN.value,
        is_active=True,
    )
    db_session.add(second_admin)
    await db_session.flush()

    await service.approve_override(
        actor_user_id=second_admin.user_id,
        override_id=override.id,
    )
    audit_log_service.reset_mock()

    with pytest.raises(
        ValueError,
        match="only requested overrides can be approved",
    ):
        await service.approve_override(
            actor_user_id=admin_user.user_id,
            override_id=override.id,
        )

    audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_reject_override_rejects_already_rejected(
    db_session,
    admin_user,
    user,
):
    admin_user.role = AdminRole.SUPER_ADMIN.value
    await db_session.flush()

    review_case = await create_review_case(db_session, user)
    audit_log_service = AsyncMock()
    service = UnderwritingOverrideService(
        session=db_session,
        audit_log_service=audit_log_service,
    )

    override = await create_override(
        service=service,
        admin_user=admin_user,
        review_case=review_case,
    )
    audit_log_service.reset_mock()

    second_user = User(
        phone_number=f"9{uuid4().int % 100_000_000:08d}",
    )
    db_session.add(second_user)
    await db_session.flush()

    second_admin = AdminUser(
        user_id=second_user.id,
        role=AdminRole.SUPER_ADMIN.value,
        is_active=True,
    )
    db_session.add(second_admin)
    await db_session.flush()

    await service.reject_override(
        actor_user_id=second_admin.user_id,
        override_id=override.id,
    )
    audit_log_service.reset_mock()

    with pytest.raises(
        ValueError,
        match="only requested overrides can be rejected",
    ):
        await service.reject_override(
            actor_user_id=admin_user.user_id,
            override_id=override.id,
        )

    audit_log_service.record_admin_action.assert_not_awaited()
