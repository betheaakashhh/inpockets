from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.assessment import AssessmentContext
from app.domain.affordability import (
    AffordabilityAssessmentStatus,
    AffordabilityFactors,
    AffordabilityAssessmentResult,
    AffordabilitySourceType,
)
from app.domain.risk import (
    RiskAssessmentStatus,
    RiskBand,
    RiskAction,
    RiskEngineResult,
    RiskFactor,
    RiskFlag,
)
from app.services.assessment_orchestrator import AssessmentOrchestrator


@pytest.fixture
def ids():
    return {
        "user_id": uuid4(),
        "application_id": uuid4(),
        "consent_id": uuid4(),
    }


@pytest.fixture
def application(ids):
    return SimpleNamespace(
        id=ids["application_id"],
        user_id=ids["user_id"],
        requested_amount=Decimal("50000"),
        requested_tenure_days=90,
    )


@pytest.fixture
def context(ids):
    return AssessmentContext(
        user_id=ids["user_id"],
        loan_application_id=ids["application_id"],
        requested_amount=Decimal("50000"),
        requested_tenure_days=90,
        context_version="assessment-context-v1",
    )


@pytest.fixture
def credit_assessment():
    return SimpleNamespace(
        bureau_score=742,
        delinquent_accounts=1,
        recent_inquiries=2,
    )


@pytest.fixture
def fraud_assessment():
    return SimpleNamespace(
        risk_level="LOW",
    )


@pytest.fixture
def affordability_result():
    return AffordabilityAssessmentResult(
        source_type=AffordabilitySourceType.CUSTOMER_DECLARED,
        source_reference="internal",
        status=AffordabilityAssessmentStatus.COMPLETED,
        factors=AffordabilityFactors(
            monthly_income=Decimal("80000"),
            monthly_obligations=Decimal("20000"),
            requested_amount=Decimal("50000"),
            requested_tenure_days=90,
            disposable_monthly_income=Decimal("60000"),
            existing_obligation_ratio=Decimal("0.25"),
        ),
    )


@pytest.fixture
def risk_result():
    return RiskEngineResult(
        model_version="risk-scorecard-v1",
        status=RiskAssessmentStatus.COMPLETED,
        risk_score=Decimal("18.00"),
        risk_band=RiskBand.LOW,
        recommended_action=RiskAction.ASSESS,
        factors=(
            RiskFactor(
                code="CREDIT_SCORE",
                description="Credit score contribution",
                category="credit",
                impact="positive",
                value="742",
            ),
        ),
        flags=(
            RiskFlag(
                code="MISSING_IDENTITY_SIGNAL",
                description="Identity signal unavailable",
                severity="LOW",
            ),
        ),
    )


class FakeCreditService:
    def __init__(self, assessment):
        self.assessment = assessment
        self.calls = []

    async def assess(self, **kwargs):
        self.calls.append(kwargs)
        return self.assessment


class FakeFraudService:
    def __init__(self, assessment):
        self.assessment = assessment
        self.calls = []

    async def assess(self, **kwargs):
        self.calls.append(kwargs)
        return self.assessment


class FakeAffordabilityService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def assess(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeRiskEngine:
    def __init__(self, result):
        self.result = result
        self.inputs = []

    def assess(self, data):
        self.inputs.append(data)
        return self.result


class FakeRiskRepository:
    def __init__(self, latest=None):
        self.latest = latest
        self.created = []

    async def get_latest_for_loan_application(self, application_id):
        return self.latest

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(**kwargs)


@pytest.mark.asyncio
async def test_orchestrator_runs_all_components_and_persists_risk(
    ids,
    application,
    context,
    credit_assessment,
    fraud_assessment,
    affordability_result,
    risk_result,
):
    credit_service = FakeCreditService(credit_assessment)
    fraud_service = FakeFraudService(fraud_assessment)
    affordability_service = FakeAffordabilityService(
        affordability_result
    )
    risk_engine = FakeRiskEngine(risk_result)
    repository = FakeRiskRepository()

    orchestrator = AssessmentOrchestrator(
        credit_service=credit_service,
        fraud_service=fraud_service,
        affordability_service=affordability_service,
        risk_engine=risk_engine,
        risk_repository=repository,
    )

    result = await orchestrator.assess(
        context=context,
        application=application,
        consent_id=ids["consent_id"],
        monthly_income=Decimal("80000"),
        monthly_obligations=Decimal("20000"),
    )

    assert result.model_version == "risk-scorecard-v1"

    assert len(credit_service.calls) == 1
    assert credit_service.calls[0]["user_id"] == ids["user_id"]
    assert credit_service.calls[0]["application_id"] == ids["application_id"]
    assert credit_service.calls[0]["consent_id"] == ids["consent_id"]

    assert len(fraud_service.calls) == 1
    assert fraud_service.calls[0]["user_id"] == ids["user_id"]
    assert fraud_service.calls[0]["application_id"] == ids["application_id"]

    assert len(affordability_service.calls) == 1
    assert (
        affordability_service.calls[0]["monthly_income"]
        == Decimal("80000")
    )
    assert (
        affordability_service.calls[0]["monthly_obligations"]
        == Decimal("20000")
    )

    assert len(risk_engine.inputs) == 1

    risk_input = risk_engine.inputs[0]

    assert risk_input.credit_score == 742
    assert risk_input.delinquent_accounts == 1
    assert risk_input.recent_inquiries == 2
    assert risk_input.fraud_risk_level == "LOW"

    assert risk_input.monthly_income == Decimal("80000")
    assert risk_input.monthly_obligations == Decimal("20000")
    assert risk_input.disposable_monthly_income == Decimal("60000")
    assert risk_input.existing_obligation_ratio == Decimal("0.25")

    assert risk_input.requested_amount == Decimal("50000")
    assert risk_input.requested_tenure_days == 90

    assert len(repository.created) == 1

    persisted = repository.created[0]

    assert persisted["loan_application_id"] == ids["application_id"]
    assert persisted["user_id"] == ids["user_id"]
    assert persisted["model_version"] == "risk-scorecard-v1"
    assert persisted["status"] == "COMPLETED"
    assert persisted["risk_score"] == Decimal("18.00")
    assert persisted["risk_band"] == "LOW"
    assert persisted["recommended_action"] == "ASSESS"

    assert persisted["factors"] == [
        {
            "code": "CREDIT_SCORE",
            "description": "Credit score contribution",
            "category": "credit",
            "impact": "positive",
            "value": "742",
        }
    ]

    assert persisted["flags"] == [
        {
            "code": "MISSING_IDENTITY_SIGNAL",
            "description": "Identity signal unavailable",
            "severity": "LOW",
        }
    ]


@pytest.mark.asyncio
async def test_existing_risk_assessment_is_reused(
    ids,
    application,
    context,
    credit_assessment,
    fraud_assessment,
    affordability_result,
    risk_result,
):
    existing = SimpleNamespace(
        id=uuid4(),
        model_version="risk-scorecard-v1",
        risk_score=Decimal("22.00"),
    )

    credit_service = FakeCreditService(credit_assessment)
    fraud_service = FakeFraudService(fraud_assessment)
    affordability_service = FakeAffordabilityService(
        affordability_result
    )
    risk_engine = FakeRiskEngine(risk_result)
    repository = FakeRiskRepository(latest=existing)

    orchestrator = AssessmentOrchestrator(
        credit_service=credit_service,
        fraud_service=fraud_service,
        affordability_service=affordability_service,
        risk_engine=risk_engine,
        risk_repository=repository,
    )

    result = await orchestrator.assess(
        context=context,
        application=application,
        consent_id=ids["consent_id"],
        monthly_income=Decimal("80000"),
        monthly_obligations=Decimal("20000"),
    )

    assert result is existing
    assert credit_service.calls == []
    assert fraud_service.calls == []
    assert affordability_service.calls == []
    assert risk_engine.inputs == []
    assert repository.created == []


@pytest.mark.asyncio
async def test_context_application_mismatch_is_rejected(
    ids,
    application,
    credit_assessment,
    fraud_assessment,
    affordability_result,
    risk_result,
):
    context = AssessmentContext(
        user_id=ids["user_id"],
        loan_application_id=uuid4(),
        requested_amount=Decimal("50000"),
        requested_tenure_days=90,
    )

    orchestrator = AssessmentOrchestrator(
        credit_service=FakeCreditService(credit_assessment),
        fraud_service=FakeFraudService(fraud_assessment),
        affordability_service=FakeAffordabilityService(
            affordability_result
        ),
        risk_engine=FakeRiskEngine(risk_result),
        risk_repository=FakeRiskRepository(),
    )

    with pytest.raises(
        ValueError,
        match="assessment context does not match loan application",
    ):
        await orchestrator.assess(
            context=context,
            application=application,
            consent_id=ids["consent_id"],
            monthly_income=Decimal("80000"),
            monthly_obligations=Decimal("20000"),
        )


@pytest.mark.asyncio
async def test_application_user_mismatch_is_rejected(
    ids,
    application,
    context,
    credit_assessment,
    fraud_assessment,
    affordability_result,
    risk_result,
):
    application.user_id = uuid4()

    orchestrator = AssessmentOrchestrator(
        credit_service=FakeCreditService(credit_assessment),
        fraud_service=FakeFraudService(fraud_assessment),
        affordability_service=FakeAffordabilityService(
            affordability_result
        ),
        risk_engine=FakeRiskEngine(risk_result),
        risk_repository=FakeRiskRepository(),
    )

    with pytest.raises(
        ValueError,
        match="loan application does not belong to user",
    ):
        await orchestrator.assess(
            context=context,
            application=application,
            consent_id=ids["consent_id"],
            monthly_income=Decimal("80000"),
            monthly_obligations=Decimal("20000"),
        )