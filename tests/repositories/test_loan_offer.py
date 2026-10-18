
import uuid
from decimal import Decimal

import pytest

from app.models.loan_application import LoanApplication
from app.repositories.loan_offer import LoanOfferRepository


async def create_application(db_session, user, application_number):
    application = LoanApplication(
        application_number=application_number,
        user_id=user.id,
        status="MANUAL_REVIEW",
        requested_amount=Decimal("5000.00"),
        requested_tenure_days=30,
    )
    db_session.add(application)
    await db_session.flush()
    return application


@pytest.mark.asyncio
async def test_create_and_get_loan_offer(db_session, user):
    application = await create_application(
        db_session, user, "INP-OFFER-TEST-001"
    )
    repository = LoanOfferRepository(db_session)

    offer = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        version=1,
        principal_amount=Decimal("4500.00"),
        tenure_days=30,
        commercial_terms={
            "annual_interest_rate": "18.00",
            "processing_fee": "100.00",
            "currency": "INR",
        },
    )

    assert offer.id is not None
    assert offer.loan_application_id == application.id
    assert offer.user_id == user.id
    assert offer.version == 1
    assert offer.principal_amount == Decimal("4500.00")
    assert offer.tenure_days == 30
    assert offer.status == "DRAFT"
    assert offer.commercial_terms["currency"] == "INR"

    fetched = await repository.get_by_id(offer_id=offer.id)

    assert fetched is not None
    assert fetched.id == offer.id


@pytest.mark.asyncio
async def test_get_missing_loan_offer_returns_none(db_session):
    repository = LoanOfferRepository(db_session)

    result = await repository.get_by_id(offer_id=uuid.uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_list_offers_by_application_orders_by_version(
    db_session, user
):
    application = await create_application(
        db_session, user, "INP-OFFER-TEST-002"
    )
    repository = LoanOfferRepository(db_session)

    first = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        version=1,
        principal_amount=Decimal("4000.00"),
        tenure_days=30,
        commercial_terms={"currency": "INR"},
    )
    second = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        version=2,
        principal_amount=Decimal("4500.00"),
        tenure_days=45,
        commercial_terms={"currency": "INR"},
    )

    offers = await repository.list_by_application_id(
        loan_application_id=application.id
    )

    assert [offer.version for offer in offers] == [2, 1]
    assert offers[0].id == second.id
    assert offers[1].id == first.id


@pytest.mark.asyncio
async def test_list_offers_by_user_id(db_session, user):
    application = await create_application(
        db_session, user, "INP-OFFER-TEST-003"
    )
    repository = LoanOfferRepository(db_session)

    offer = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        version=1,
        principal_amount=Decimal("3500.00"),
        tenure_days=30,
        commercial_terms={"currency": "INR"},
    )

    offers = await repository.list_by_user_id(user_id=user.id)

    assert any(item.id == offer.id for item in offers)


@pytest.mark.asyncio
async def test_get_latest_offer_for_application(db_session, user):
    application = await create_application(
        db_session, user, "INP-OFFER-TEST-004"
    )
    repository = LoanOfferRepository(db_session)

    await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        version=1,
        principal_amount=Decimal("3000.00"),
        tenure_days=30,
        commercial_terms={"currency": "INR"},
    )
    latest = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        version=2,
        principal_amount=Decimal("3200.00"),
        tenure_days=45,
        commercial_terms={"currency": "INR"},
    )

    result = await repository.get_latest_for_application(
        loan_application_id=application.id
    )

    assert result is not None
    assert result.id == latest.id
    assert result.version == 2


@pytest.mark.asyncio
async def test_get_latest_offer_for_empty_application_returns_none(
    db_session, user
):
    application = await create_application(
        db_session, user, "INP-OFFER-TEST-005"
    )
    repository = LoanOfferRepository(db_session)

    result = await repository.get_latest_for_application(
        loan_application_id=application.id
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_offer_by_id_for_update(db_session, user):
    application = await create_application(
        db_session, user, "INP-OFFER-TEST-006"
    )
    repository = LoanOfferRepository(db_session)

    offer = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        version=1,
        principal_amount=Decimal("2500.00"),
        tenure_days=30,
        commercial_terms={"currency": "INR"},
    )

    locked = await repository.get_by_id_for_update(offer_id=offer.id)

    assert locked is not None
    assert locked.id == offer.id
    assert locked.status == "DRAFT"
