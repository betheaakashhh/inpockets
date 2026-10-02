from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.affordability import (
    AffordabilityAssessmentStatus,
    AffordabilitySourceType,
)
from app.services.affordability_assessment import (
    AffordabilityAssessmentService,
)


def make_application(
    *,
    user_id,
    requested_amount=Decimal("10000.00"),
    requested_tenure_days=30,
):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        requested_amount=requested_amount,
        requested_tenure_days=requested_tenure_days,
    )


class FakeRepository:
    def __init__(self, latest=None):
        self.latest = latest
        self.created = []

    async def get_latest_for_loan_application(self, loan_application_id):
        return self.latest

    async def create(self, **kwargs):
        assessment = SimpleNamespace(
            id=uuid4(),
            failure_reason=None,
            **kwargs,
        )
        self.created.append(assessment)
        return assessment


def make_service(repository):
    service = object.__new__(AffordabilityAssessmentService)
    service.repository = repository
    return service


@pytest.mark.asyncio
async def test_assess_calculates_affordability_factors():
    user_id = uuid4()
    application = make_application(user_id=user_id)

    repository = FakeRepository()
    service = make_service(repository)

    result = await service.assess(
        user_id=user_id,
        application=application,
        monthly_income=Decimal("50000.00"),
        monthly_obligations=Decimal("15000.00"),
    )

    assert result.status == AffordabilityAssessmentStatus.COMPLETED
    assert result.source_type == AffordabilitySourceType.CUSTOMER_DECLARED

    assert result.factors.monthly_income == Decimal("50000.00")
    assert result.factors.monthly_obligations == Decimal("15000.00")
    assert result.factors.requested_amount == Decimal("10000.00")
    assert result.factors.requested_tenure_days == 30
    assert result.factors.disposable_monthly_income == Decimal("35000.00")
    assert result.factors.existing_obligation_ratio == Decimal("0.3")


@pytest.mark.asyncio
async def test_assess_rejects_zero_income():
    user_id = uuid4()
    application = make_application(user_id=user_id)

    service = make_service(FakeRepository())

    with pytest.raises(
        ValueError,
        match="monthly_income must be greater than zero",
    ):
        await service.assess(
            user_id=user_id,
            application=application,
            monthly_income=Decimal("0"),
            monthly_obligations=Decimal("0"),
        )


@pytest.mark.asyncio
async def test_assess_rejects_negative_obligations():
    user_id = uuid4()
    application = make_application(user_id=user_id)

    service = make_service(FakeRepository())

    with pytest.raises(
        ValueError,
        match="monthly_obligations cannot be negative",
    ):
        await service.assess(
            user_id=user_id,
            application=application,
            monthly_income=Decimal("50000"),
            monthly_obligations=Decimal("-1"),
        )


@pytest.mark.asyncio
async def test_assess_rejects_application_from_different_user():
    owner_id = uuid4()
    different_user_id = uuid4()

    application = make_application(user_id=owner_id)

    service = make_service(FakeRepository())

    with pytest.raises(
        ValueError,
        match="loan application does not belong to user",
    ):
        await service.assess(
            user_id=different_user_id,
            application=application,
            monthly_income=Decimal("50000"),
            monthly_obligations=Decimal("10000"),
        )


@pytest.mark.asyncio
async def test_assess_reuses_completed_same_version():
    user_id = uuid4()
    application = make_application(user_id=user_id)

    existing = SimpleNamespace(
        id=uuid4(),
        status=AffordabilityAssessmentStatus.COMPLETED.value,
        calculation_version=AffordabilityAssessmentService.CALCULATION_VERSION,
        source_type=AffordabilitySourceType.CUSTOMER_DECLARED.value,
        source_reference="internal",
        monthly_income=Decimal("50000"),
        monthly_obligations=Decimal("10000"),
        requested_amount=Decimal("10000"),
        requested_tenure_days=30,
        disposable_monthly_income=Decimal("40000"),
        existing_obligation_ratio=Decimal("0.2"),
        failure_reason=None,
    )

    repository = FakeRepository(latest=existing)
    service = make_service(repository)

    result = await service.assess(
        user_id=user_id,
        application=application,
        monthly_income=Decimal("99999"),
        monthly_obligations=Decimal("1"),
    )

    assert result.factors.monthly_income == Decimal("50000")
    assert result.factors.monthly_obligations == Decimal("10000")
    assert result.factors.disposable_monthly_income == Decimal("40000")
    assert result.factors.existing_obligation_ratio == Decimal("0.2")

    assert repository.created == []


@pytest.mark.asyncio
async def test_assess_persists_calculation_version_and_snapshot():
    user_id = uuid4()
    application = make_application(user_id=user_id)

    repository = FakeRepository()
    service = make_service(repository)

    await service.assess(
        user_id=user_id,
        application=application,
        monthly_income=Decimal("60000"),
        monthly_obligations=Decimal("20000"),
    )

    assert len(repository.created) == 1

    created = repository.created[0]

    assert (
        created.calculation_version
        == AffordabilityAssessmentService.CALCULATION_VERSION
    )

    assert created.feature_snapshot["monthly_income"] == "60000"
    assert created.feature_snapshot["monthly_obligations"] == "20000"
    assert created.feature_snapshot["disposable_monthly_income"] == "40000"
    assert created.feature_snapshot["existing_obligation_ratio"] == "0.3333333333333333333333333333"


@pytest.mark.asyncio
async def test_assess_rejects_invalid_application_amount():
    user_id = uuid4()
    application = make_application(
        user_id=user_id,
        requested_amount=Decimal("0"),
    )

    service = make_service(FakeRepository())

    with pytest.raises(
        ValueError,
        match="requested_amount must be greater than zero",
    ):
        await service.assess(
            user_id=user_id,
            application=application,
            monthly_income=Decimal("50000"),
            monthly_obligations=Decimal("10000"),
        )


@pytest.mark.asyncio
async def test_assess_rejects_invalid_application_tenure():
    user_id = uuid4()
    application = make_application(
        user_id=user_id,
        requested_tenure_days=0,
    )

    service = make_service(FakeRepository())

    with pytest.raises(
        ValueError,
        match="requested_tenure_days must be greater than zero",
    ):
        await service.assess(
            user_id=user_id,
            application=application,
            monthly_income=Decimal("50000"),
            monthly_obligations=Decimal("10000"),
        )

