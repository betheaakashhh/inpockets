import uuid
from decimal import Decimal

import pytest #type: ignore

from app.models.loan_application import LoanApplication
from app.repositories.loan_application import LoanApplicationRepository


@pytest.mark.asyncio
async def test_create_and_get_loan_application(db_session, user):
    repository = LoanApplicationRepository(db_session)

    application = await repository.create(
        application_number="INP-TEST-000001",
        user_id=user.id,
        status="DRAFT",
        requested_amount=Decimal("5000.00"),
        requested_tenure_days=30,
    )

    assert application.id is not None
    assert application.application_number == "INP-TEST-000001"
    assert application.user_id == user.id
    assert application.status == "DRAFT"
    assert application.requested_amount == Decimal("5000.00")
    assert application.requested_tenure_days == 30

    fetched = await repository.get_by_id(
        application_id=application.id,
    )

    assert fetched is not None
    assert fetched.id == application.id


@pytest.mark.asyncio
async def test_get_by_application_number(db_session, user):
    repository = LoanApplicationRepository(db_session)

    application = await repository.create(
        application_number="INP-TEST-000002",
        user_id=user.id,
        status="DRAFT",
        requested_amount=Decimal("2500.00"),
        requested_tenure_days=15,
    )

    fetched = await repository.get_by_application_number(
        application_number="INP-TEST-000002",
    )

    assert fetched is not None
    assert fetched.id == application.id


@pytest.mark.asyncio
async def test_list_by_user_id(db_session, user):
    repository = LoanApplicationRepository(db_session)

    first = await repository.create(
        application_number="INP-TEST-000003",
        user_id=user.id,
        status="DRAFT",
        requested_amount=Decimal("3000.00"),
        requested_tenure_days=20,
    )

    second = await repository.create(
        application_number="INP-TEST-000004",
        user_id=user.id,
        status="SUBMITTED",
        requested_amount=Decimal("7000.00"),
        requested_tenure_days=45,
    )

    applications = await repository.list_by_user_id(
        user_id=user.id,
    )

    ids = {application.id for application in applications}

    assert first.id in ids
    assert second.id in ids


@pytest.mark.asyncio
async def test_create_and_list_events(db_session, user):
    repository = LoanApplicationRepository(db_session)

    application = await repository.create(
        application_number="INP-TEST-000005",
        user_id=user.id,
        status="DRAFT",
        requested_amount=Decimal("5000.00"),
        requested_tenure_days=30,
    )

    event = await repository.create_event(
        application_id=application.id,
        event_type="APPLICATION_CREATED",
        previous_status=None,
        new_status="DRAFT",
        actor_type="CUSTOMER",
        actor_id=user.id,
        event_metadata={"source": "test"},
    )

    assert event.id is not None
    assert event.application_id == application.id
    assert event.event_type == "APPLICATION_CREATED"
    assert event.previous_status is None
    assert event.new_status == "DRAFT"
    assert event.actor_type == "CUSTOMER"
    assert event.actor_id == user.id
    assert event.event_metadata == {"source": "test"}

    events = await repository.list_events(
        application_id=application.id,
    )

    assert len(events) == 1
    assert events[0].id == event.id


@pytest.mark.asyncio
async def test_get_by_id_for_update(db_session, user):
    repository = LoanApplicationRepository(db_session)

    application = await repository.create(
        application_number="INP-TEST-000006",
        user_id=user.id,
        status="PROCESSING",
        requested_amount=Decimal("9000.00"),
        requested_tenure_days=60,
    )

    locked = await repository.get_by_id_for_update(
        application_id=application.id,
    )

    assert locked is not None
    assert locked.id == application.id
    assert locked.status == "PROCESSING"


@pytest.mark.asyncio
async def test_get_missing_application_returns_none(db_session):
    repository = LoanApplicationRepository(db_session)

    result = await repository.get_by_id(
        application_id=uuid.uuid4(),
    )

    assert result is None