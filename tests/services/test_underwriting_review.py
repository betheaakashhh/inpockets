from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domain.admin import AdminPermission
from app.domain.underwriting import UnderwritingReviewCase, UnderwritingReviewStatus
from app.services.underwriting_review import UnderwritingReviewService


def make_case(*, status=UnderwritingReviewStatus.QUEUED, assigned_admin_user_id=None):
    return UnderwritingReviewCase(
        id=uuid4(), loan_application_id=uuid4(), user_id=uuid4(),
        status=status, assigned_admin_user_id=assigned_admin_user_id,
        opened_at=datetime.now(timezone.utc),
        closed_at=(datetime.now(timezone.utc) if status in {
            UnderwritingReviewStatus.APPROVED, UnderwritingReviewStatus.REJECTED,
            UnderwritingReviewStatus.CLOSED,
        } else None),
    )


def make_service():
    review_repository = AsyncMock()
    admin_authorization = AsyncMock()
    admin_authorization.admin_user_repository = AsyncMock()
    audit_log_service = AsyncMock()
    service = UnderwritingReviewService(
        review_case_repository=review_repository,
        admin_authorization_service=admin_authorization,
        audit_log_service=audit_log_service,
    )
    return service, review_repository, admin_authorization, audit_log_service


@pytest.mark.asyncio
async def test_authorized_admin_can_assign_case():
    service, repository, authorization, audit_log_service = make_service()
    actor_user_id = uuid4(); 
    assignee_admin_user_id = uuid4();
    case = make_case()
    assigned_case = UnderwritingReviewCase(
        id=case.id, loan_application_id=case.loan_application_id, user_id=case.user_id,
        status=UnderwritingReviewStatus.ASSIGNED,
        assigned_admin_user_id=assignee_admin_user_id, opened_at=case.opened_at,
    )
    repository.get_by_id.return_value = case
    repository.assign.return_value = assigned_case
    result = await service.assign_case(actor_user_id=actor_user_id, case_id=case.id, assignee_admin_user_id=assignee_admin_user_id)
    assert result == assigned_case
    repository.assign.assert_awaited_once_with(case_id=case.id, admin_user_id=assignee_admin_user_id)
    audit_log_service.record_admin_action.assert_awaited_once()
    audit = audit_log_service.record_admin_action.await_args.kwargs
    assert audit["actor_user_id"] == actor_user_id
    assert audit["action"] == "UNDERWRITING_CASE_ASSIGNED"
    assert audit["entity_type"] == "underwriting_review_case"
    assert audit["entity_id"] == str(case.id)
    assert audit["old_value"]["status"] == UnderwritingReviewStatus.QUEUED.value
    assert audit["new_value"]["status"] == UnderwritingReviewStatus.ASSIGNED.value


@pytest.mark.asyncio
async def test_unauthorized_admin_cannot_assign_case():
    service, repository, authorization, audit_log_service = make_service(); case = make_case()
    authorization.require_permission.side_effect = PermissionError("permission denied")
    with pytest.raises(PermissionError, match="permission denied"):
        await service.assign_case(actor_user_id=uuid4(), case_id=case.id, assignee_admin_user_id=uuid4())
    repository.get_by_id.assert_not_awaited(); 
    repository.assign.assert_not_awaited()
    audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_assigned_admin_can_start_review():
    service, repository, authorization, audit_log_service = make_service()
    actor_user_id = uuid4(); admin_user_id = uuid4()
    case = make_case(status=UnderwritingReviewStatus.ASSIGNED, assigned_admin_user_id=admin_user_id)
    actor_admin = type("AdminUserStub", (), {"id": admin_user_id})()
    repository.get_by_id.return_value = case; repository.start_review.return_value = case
    authorization.admin_user_repository.get_by_user_id.return_value = actor_admin
    result = await service.start_review(actor_user_id=actor_user_id, case_id=case.id)
    assert result == case
    authorization.require_permission.assert_awaited_once_with(user_id=actor_user_id, permission=AdminPermission.UNDERWRITING_REVIEW)
    repository.start_review.assert_awaited_once_with(case_id=case.id)
    audit_log_service.record_admin_action.assert_awaited_once()
    audit = audit_log_service.record_admin_action.await_args.kwargs
    assert audit["actor_user_id"] == actor_user_id
    assert audit["action"] == "UNDERWRITING_REVIEW_STARTED"
    assert audit["entity_type"] == "underwriting_review_case"
    assert audit["entity_id"] == str(case.id)


@pytest.mark.asyncio
async def test_different_admin_cannot_start_assigned_case():
    service, repository, authorization, audit_log_service = make_service()
    actor_user_id = uuid4(); assigned_admin_user_id = uuid4(); different_admin_user_id = uuid4()
    case = make_case(status=UnderwritingReviewStatus.ASSIGNED, assigned_admin_user_id=assigned_admin_user_id)
    actor_admin = type("AdminUserStub", (), {"id": different_admin_user_id})()
    repository.get_by_id.return_value = case
    authorization.admin_user_repository.get_by_user_id.return_value = actor_admin
    with pytest.raises(PermissionError, match="assigned to another admin"):
        await service.start_review(actor_user_id=actor_user_id, case_id=case.id)
    repository.start_review.assert_not_awaited(); audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_reviewer_cannot_approve_unless_case_is_in_review():
    service, repository, authorization, audit_log_service = make_service(); case = make_case(status=UnderwritingReviewStatus.ASSIGNED)
    repository.get_by_id.return_value = case
    with pytest.raises(ValueError, match="must be IN_REVIEW"):
        await service.approve_case(actor_user_id=uuid4(), case_id=case.id)
    authorization.require_permission.assert_awaited_once_with(user_id=authorization.require_permission.call_args.kwargs["user_id"], permission=AdminPermission.LOAN_APPROVE)
    repository.complete.assert_not_awaited(); audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_authorized_lender_admin_can_approve():
    service, repository, authorization, audit_log_service = make_service(); actor_user_id = uuid4(); case = make_case(status=UnderwritingReviewStatus.IN_REVIEW)
    approved_case = make_case(status=UnderwritingReviewStatus.APPROVED)
    repository.get_by_id.return_value = case; repository.complete.return_value = approved_case
    result = await service.approve_case(actor_user_id=actor_user_id, case_id=case.id)
    assert result == approved_case
    repository.complete.assert_awaited_once_with(case_id=case.id, status="APPROVED")
    audit_log_service.record_admin_action.assert_awaited_once()
    audit = audit_log_service.record_admin_action.await_args.kwargs
    assert audit["actor_user_id"] == actor_user_id
    assert audit["action"] == "UNDERWRITING_CASE_APPROVED"
    assert audit["entity_type"] == "underwriting_review_case"
    assert audit["entity_id"] == str(case.id)
    assert audit["old_value"]["status"] == UnderwritingReviewStatus.IN_REVIEW.value
    assert audit["new_value"]["status"] == UnderwritingReviewStatus.APPROVED.value


@pytest.mark.asyncio
async def test_authorized_lender_admin_can_reject():
    service, repository, authorization, audit_log_service = make_service(); actor_user_id = uuid4(); case = make_case(status=UnderwritingReviewStatus.IN_REVIEW)
    rejected_case = make_case(status=UnderwritingReviewStatus.REJECTED)
    repository.get_by_id.return_value = case; repository.complete.return_value = rejected_case
    result = await service.reject_case(actor_user_id=actor_user_id, case_id=case.id)
    assert result == rejected_case
    repository.complete.assert_awaited_once_with(case_id=case.id, status="REJECTED")
    audit_log_service.record_admin_action.assert_awaited_once()
    audit = audit_log_service.record_admin_action.await_args.kwargs
    assert audit["actor_user_id"] == actor_user_id
    assert audit["action"] == "UNDERWRITING_CASE_REJECTED"
    assert audit["entity_type"] == "underwriting_review_case"
    assert audit["entity_id"] == str(case.id)
    assert audit["old_value"]["status"] == UnderwritingReviewStatus.IN_REVIEW.value
    assert audit["new_value"]["status"] == UnderwritingReviewStatus.REJECTED.value


@pytest.mark.asyncio
async def test_non_approver_cannot_approve():
    service, repository, authorization, audit_log_service = make_service()
    authorization.require_permission.side_effect = PermissionError("role UNDERWRITER does not have permission LOAN_APPROVE")
    with pytest.raises(PermissionError, match="LOAN_APPROVE"):
        await service.approve_case(actor_user_id=uuid4(), case_id=uuid4())
    repository.get_by_id.assert_not_awaited(); repository.complete.assert_not_awaited(); audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_closed_case_cannot_be_decided_again():
    service, repository, authorization, audit_log_service = make_service(); case = make_case(status=UnderwritingReviewStatus.APPROVED)
    repository.get_by_id.return_value = case
    with pytest.raises(ValueError, match="already closed|must be IN_REVIEW"):
        await service.reject_case(actor_user_id=uuid4(), case_id=case.id)
    repository.complete.assert_not_awaited(); audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_case_raises_not_found():
    service, repository, authorization, audit_log_service = make_service(); repository.get_by_id.return_value = None
    with pytest.raises(ValueError, match="underwriting review case not found"):
        await service.assign_case(actor_user_id=uuid4(), case_id=uuid4(), assignee_admin_user_id=uuid4())
    repository.assign.assert_not_awaited(); audit_log_service.record_admin_action.assert_not_awaited()

@pytest.mark.asyncio
async def test_authorized_admin_can_close_case_with_audit():
    service, repository, authorization, audit_log_service = make_service()

    actor_user_id = uuid4()
    case = make_case(status=UnderwritingReviewStatus.IN_REVIEW)
    closed_case = make_case(status=UnderwritingReviewStatus.CLOSED)

    repository.get_by_id.return_value = case
    repository.complete.return_value = closed_case

    result = await service.close_case(
        actor_user_id=actor_user_id,
        case_id=case.id,
    )

    assert result == closed_case

    authorization.require_permission.assert_awaited_once_with(
        user_id=actor_user_id,
        permission=AdminPermission.UNDERWRITING_REVIEW,
    )

    repository.complete.assert_awaited_once_with(
        case_id=case.id,
        status="CLOSED",
    )

    audit_log_service.record_admin_action.assert_awaited_once()

    audit = audit_log_service.record_admin_action.await_args.kwargs

    assert audit["actor_user_id"] == actor_user_id
    assert audit["action"] == "UNDERWRITING_CASE_CLOSED"
    assert audit["entity_type"] == "underwriting_review_case"
    assert audit["entity_id"] == str(case.id)
    assert audit["old_value"] == {
        "status": UnderwritingReviewStatus.IN_REVIEW.value,
    }
    assert audit["new_value"] == {
        "status": UnderwritingReviewStatus.CLOSED.value,
    }

@pytest.mark.asyncio
async def test_unauthorized_admin_cannot_close_case():
    service, repository, authorization, audit_log_service = make_service()

    authorization.require_permission.side_effect = PermissionError(
        "permission denied"
    )

    with pytest.raises(PermissionError, match="permission denied"):
        await service.close_case(
            actor_user_id=uuid4(),
            case_id=uuid4(),
        )

    repository.get_by_id.assert_not_awaited()
    repository.complete.assert_not_awaited()
    audit_log_service.record_admin_action.assert_not_awaited()