from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domain.admin import AdminPermission
from app.domain.underwriting import UnderwritingReviewCase, UnderwritingReviewStatus
from app.services.underwriting_review import UnderwritingReviewService


def make_case(
    *,
    status: UnderwritingReviewStatus = UnderwritingReviewStatus.QUEUED,
    assigned_admin_user_id=None,
) -> UnderwritingReviewCase:
    return UnderwritingReviewCase(
        id=uuid4(),
        loan_application_id=uuid4(),
        user_id=uuid4(),
        status=status,
        assigned_admin_user_id=assigned_admin_user_id,
    )


def make_service():
    repository = AsyncMock()
    authorization = AsyncMock()

    admin_user_repository = AsyncMock()
    authorization.admin_user_repository = admin_user_repository

    service = UnderwritingReviewService(
        review_case_repository=repository,
        admin_authorization_service=authorization,
    )

    return service, repository, authorization, admin_user_repository


@pytest.mark.asyncio
async def test_authorized_reviewer_can_list_queue():
    service, repository, authorization, _ = make_service()

    cases = [make_case(), make_case()]
    repository.list_by_status.return_value = cases

    result = await service.list_queue(actor_user_id=uuid4())

    authorization.require_permission.assert_awaited_once_with(
        user_id=authorization.require_permission.await_args.kwargs["user_id"],
        permission=AdminPermission.UNDERWRITING_REVIEW,
    )
    repository.list_by_status.assert_awaited_once_with(status="QUEUED")
    assert result == cases


@pytest.mark.asyncio
async def test_unauthorized_role_cannot_list_queue():
    service, repository, authorization, _ = make_service()
    authorization.require_permission.side_effect = PermissionError(
        "role does not have permission"
    )

    with pytest.raises(PermissionError, match="role does not have permission"):
        await service.list_queue(actor_user_id=uuid4())

    repository.list_by_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_can_list_my_assigned_cases():
    service, repository, authorization, admin_user_repository = make_service()

    actor_user_id = uuid4()
    admin_record = type("AdminUserRecord", (), {"id": uuid4()})()
    admin_user_repository.get_by_user_id.return_value = admin_record

    cases = [
        make_case(
            status=UnderwritingReviewStatus.ASSIGNED,
            assigned_admin_user_id=admin_record.id,
        )
    ]
    repository.list_by_assigned_admin.return_value = cases

    result = await service.list_my_cases(
        actor_user_id=actor_user_id,
        status="ASSIGNED",
    )

    authorization.require_permission.assert_awaited_once_with(
        user_id=actor_user_id,
        permission=AdminPermission.UNDERWRITING_REVIEW,
    )
    repository.list_by_assigned_admin.assert_awaited_once_with(
        admin_user_id=admin_record.id,
        status="ASSIGNED",
    )
    assert result == cases


@pytest.mark.asyncio
async def test_my_cases_requires_admin_record():
    service, repository, authorization, admin_user_repository = make_service()

    admin_user_repository.get_by_user_id.return_value = None

    with pytest.raises(PermissionError, match="user is not an admin"):
        await service.list_my_cases(actor_user_id=uuid4())

    repository.list_by_assigned_admin.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_can_claim_queued_case():
    service, repository, authorization, admin_user_repository = make_service()

    actor_user_id = uuid4()
    admin_record = type("AdminUserRecord", (), {"id": uuid4()})()
    case = make_case()

    admin_user_repository.get_by_user_id.return_value = admin_record
    repository.get_by_id.return_value = case
    repository.assign.return_value = case

    result = await service.claim_case(
        actor_user_id=actor_user_id,
        case_id=case.id,
    )

    authorization.require_permission.assert_awaited_once_with(
        user_id=actor_user_id,
        permission=AdminPermission.UNDERWRITING_ASSIGN,
    )
    repository.assign.assert_awaited_once_with(
        case_id=case.id,
        admin_user_id=admin_record.id,
    )
    assert result == case


@pytest.mark.asyncio
async def test_claim_changes_case_to_assigned_via_repository():
    service, repository, authorization, admin_user_repository = make_service()

    admin_record = type("AdminUserRecord", (), {"id": uuid4()})()
    case = make_case()

    admin_user_repository.get_by_user_id.return_value = admin_record
    repository.get_by_id.return_value = case

    assigned_case = make_case(
        status=UnderwritingReviewStatus.ASSIGNED,
        assigned_admin_user_id=admin_record.id,
    )
    repository.assign.return_value = assigned_case

    result = await service.claim_case(
        actor_user_id=uuid4(),
        case_id=case.id,
    )

    assert result.status == UnderwritingReviewStatus.ASSIGNED
    assert result.assigned_admin_user_id == admin_record.id


@pytest.mark.asyncio
async def test_cannot_claim_already_assigned_case():
    service, repository, authorization, admin_user_repository = make_service()

    admin_user_repository.get_by_user_id.return_value = type(
        "AdminUserRecord", (), {"id": uuid4()}
    )()

    case = make_case(
        status=UnderwritingReviewStatus.ASSIGNED,
        assigned_admin_user_id=uuid4(),
    )
    repository.get_by_id.return_value = case

    with pytest.raises(
        ValueError,
        match="only QUEUED underwriting review cases can be claimed",
    ):
        await service.claim_case(
            actor_user_id=uuid4(),
            case_id=case.id,
        )

    repository.assign.assert_not_awaited()


@pytest.mark.asyncio
async def test_cannot_claim_in_review_case():
    service, repository, authorization, admin_user_repository = make_service()

    admin_user_repository.get_by_user_id.return_value = type(
        "AdminUserRecord", (), {"id": uuid4()}
    )()

    case = make_case(status=UnderwritingReviewStatus.IN_REVIEW)
    repository.get_by_id.return_value = case

    with pytest.raises(
        ValueError,
        match="only QUEUED underwriting review cases can be claimed",
    ):
        await service.claim_case(
            actor_user_id=uuid4(),
            case_id=case.id,
        )

    repository.assign.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_admin_cannot_claim_case():
    service, repository, authorization, admin_user_repository = make_service()

    admin_user_repository.get_by_user_id.return_value = None
    case = make_case()
    repository.get_by_id.return_value = case

    with pytest.raises(PermissionError, match="user is not an admin"):
        await service.claim_case(
            actor_user_id=uuid4(),
            case_id=case.id,
        )

    repository.assign.assert_not_awaited()


@pytest.mark.asyncio
async def test_claim_missing_case_raises_not_found():
    service, repository, authorization, admin_user_repository = make_service()

    admin_user_repository.get_by_user_id.return_value = type(
        "AdminUserRecord", (), {"id": uuid4()}
    )()
    repository.get_by_id.return_value = None

    with pytest.raises(
        ValueError,
        match="underwriting review case not found",
    ):
        await service.claim_case(
            actor_user_id=uuid4(),
            case_id=uuid4(),
        )

    repository.assign.assert_not_awaited()
