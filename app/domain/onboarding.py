from enum import StrEnum


class OnboardingStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class OnboardingStep(StrEnum):
    PROFILE = "PROFILE"
    PAN = "PAN"
    KYC = "KYC"
    IDENTITY = "IDENTITY"
    COMPLETED = "COMPLETED"


ONBOARDING_STEP_ORDER: tuple[OnboardingStep, ...] = (
    OnboardingStep.PROFILE,
    OnboardingStep.PAN,
    OnboardingStep.KYC,
    OnboardingStep.IDENTITY,
    OnboardingStep.COMPLETED,
)


def is_valid_step_transition(
    current_step: OnboardingStep,
    next_step: OnboardingStep,
) -> bool:
    """
    Allow moving forward one step or remaining on the current step.

    Backward transitions are intentionally rejected.
    """
    current_index = ONBOARDING_STEP_ORDER.index(current_step)
    next_index = ONBOARDING_STEP_ORDER.index(next_step)

    return next_index == current_index or next_index == current_index + 1