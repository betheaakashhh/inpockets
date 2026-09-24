from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.domain.loan_application import LoanApplicationStatus
from app.services.loan_application import LoanApplicationService


@pytest.mark.asyncio
async def test_create_draft():
    repository = AsyncMock()

    user_id = __import__("uuid").uuid4()

    application = type(
        "Application",
        (),
        {
            "id": __import__("uuid").uuid4(),
            "user_id": user_id,
            "status": LoanApplicationStatus.DRAFT,
        },
    )()

    repository.create.return_value = application

    service = LoanApplicationService(repository)

    result = await service.create_draft(
        user_id=user_id,
        requested_amount=Decimal("5000.00"),
        requested_tenure_days=30,
    )

    assert result is application

    repository.create.assert_awaited_once()
    repository.create_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_draft_rejects_invalid_amount():
    repository = AsyncMock()
    service = LoanApplicationService(repository)

    with pytest.raises(ValueError, match="amount"):
        await service.create_draft(
            user_id=__import__("uuid").uuid4(),
            requested_amount=Decimal("0"),
            requested_tenure_days=30,
        )

    repository.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_draft_rejects_invalid_tenure():
    repository = AsyncMock()
    service = LoanApplicationService(repository)

    with pytest.raises(ValueError, match="tenure"):
        await service.create_draft(
            user_id=__import__("uuid").uuid4(),
            requested_amount=Decimal("5000.00"),
            requested_tenure_days=0,
        )

    repository.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_draft():
    repository = AsyncMock()

    user_id = __import__("uuid").uuid4()

    application = type(
        "Application",
        (),
        {
            "id": __import__("uuid").uuid4(),
            "user_id": user_id,
            "status": LoanApplicationStatus.DRAFT,
            "submitted_at": None,
        },
    )()

    repository.get_by_id_for_update.return_value = application

    service = LoanApplicationService(repository)

    result = await service.submit(
        application_id=application.id,
        user_id=user_id,
    )

    assert result.status == LoanApplicationStatus.SUBMITTED
    assert result.submitted_at is not None

    repository.update.assert_awaited_once()
    repository.create_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_is_idempotent():
    repository = AsyncMock()

    user_id = __import__("uuid").uuid4()

    application = type(
        "Application",
        (),
        {
            "id": __import__("uuid").uuid4(),
            "user_id": user_id,
            "status": LoanApplicationStatus.SUBMITTED,
            "submitted_at": None,
        },
    )()

    repository.get_by_id_for_update.return_value = application

    service = LoanApplicationService(repository)

    result = await service.submit(
        application_id=application.id,
        user_id=user_id,
    )

    assert result is application

    repository.update.assert_not_awaited()
    repository.create_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_rejects_other_users_application():
    repository = AsyncMock()

    owner_id = __import__("uuid").uuid4()
    other_user_id = __import__("uuid").uuid4()

    application = type(
        "Application",
        (),
        {
            "id": __import__("uuid").uuid4(),
            "user_id": owner_id,
            "status": LoanApplicationStatus.DRAFT,
            "submitted_at": None,
        },
    )()

    repository.get_by_id_for_update.return_value = application

    service = LoanApplicationService(repository)

    with pytest.raises(ValueError, match="does not belong"):
        await service.submit(
            application_id=application.id,
            user_id=other_user_id,
        )

    repository.update.assert_not_awaited()
    repository.create_event.assert_not_awaited()