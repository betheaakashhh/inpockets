import pytest

from app.domain.onboarding import (
    OnboardingStep,
    is_valid_step_transition,
)


@pytest.mark.parametrize(
    ("current_step", "next_step"),
    [
        (OnboardingStep.PROFILE, OnboardingStep.PROFILE),
        (OnboardingStep.PROFILE, OnboardingStep.PAN),
        (OnboardingStep.PAN, OnboardingStep.PAN),
        (OnboardingStep.PAN, OnboardingStep.KYC),
        (OnboardingStep.KYC, OnboardingStep.KYC),
        (OnboardingStep.KYC, OnboardingStep.IDENTITY),
        (OnboardingStep.IDENTITY, OnboardingStep.IDENTITY),
        (OnboardingStep.IDENTITY, OnboardingStep.COMPLETED),
        (OnboardingStep.COMPLETED, OnboardingStep.COMPLETED),
    ],
)
def test_valid_onboarding_step_transitions(current_step, next_step):
    assert is_valid_step_transition(current_step, next_step)


@pytest.mark.parametrize(
    ("current_step", "next_step"),
    [
        (OnboardingStep.PROFILE, OnboardingStep.KYC),
        (OnboardingStep.PROFILE, OnboardingStep.IDENTITY),
        (OnboardingStep.PROFILE, OnboardingStep.COMPLETED),
        (OnboardingStep.PAN, OnboardingStep.IDENTITY),
        (OnboardingStep.PAN, OnboardingStep.COMPLETED),
        (OnboardingStep.KYC, OnboardingStep.COMPLETED),
        (OnboardingStep.PAN, OnboardingStep.PROFILE),
        (OnboardingStep.KYC, OnboardingStep.PAN),
        (OnboardingStep.IDENTITY, OnboardingStep.KYC),
        (OnboardingStep.COMPLETED, OnboardingStep.IDENTITY),
    ],
)
def test_invalid_onboarding_step_transitions(current_step, next_step):
    assert not is_valid_step_transition(current_step, next_step)