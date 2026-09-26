from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.domain.assessment import AssessmentContext, AssessmentSignal


def test_assessment_context_has_required_application_inputs():
    user_id = uuid4()
    application_id = uuid4()

    context = AssessmentContext(
        user_id=user_id,
        loan_application_id=application_id,
        requested_amount=Decimal("15000.00"),
        requested_tenure_days=30,
    )

    assert context.user_id == user_id
    assert context.loan_application_id == application_id
    assert context.requested_amount == Decimal("15000.00")
    assert context.requested_tenure_days == 30
    assert context.context_version == "assessment-context-v1"
    assert context.identity_signals == ()


def test_assessment_context_supports_normalized_signal_categories():
    signal = AssessmentSignal(
        code="PAN_VERIFIED",
        category="IDENTITY",
        value="true",
        source="internal",
        reference="pan-verification-001",
    )

    context = AssessmentContext(
        user_id=uuid4(),
        loan_application_id=uuid4(),
        requested_amount=Decimal("10000.00"),
        requested_tenure_days=30,
        identity_signals=(signal,),
        device_signals=(
            AssessmentSignal(
                code="DEVICE_VELOCITY",
                category="DEVICE",
                value="LOW",
                source="fraud-provider",
            ),
        ),
    )

    assert context.identity_signals[0].code == "PAN_VERIFIED"
    assert context.identity_signals[0].category == "IDENTITY"
    assert context.device_signals[0].code == "DEVICE_VELOCITY"


def test_assessment_context_is_versioned_and_reproducible():
    requested_at = datetime(2026, 9, 27, 10, 30, tzinfo=timezone.utc)

    context = AssessmentContext(
        user_id=uuid4(),
        loan_application_id=uuid4(),
        requested_amount=Decimal("25000.00"),
        requested_tenure_days=45,
        context_version="assessment-context-v1",
        assessment_reference="assessment-run-001",
        requested_at=requested_at,
    )

    same_context = AssessmentContext(
        user_id=context.user_id,
        loan_application_id=context.loan_application_id,
        requested_amount=context.requested_amount,
        requested_tenure_days=context.requested_tenure_days,
        context_version=context.context_version,
        assessment_reference=context.assessment_reference,
        requested_at=context.requested_at,
    )

    assert context == same_context
    assert context.context_version == "assessment-context-v1"
    assert context.requested_at == requested_at
