from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class SubmitPANRequest(BaseModel):
    pan_number: str = Field(..., min_length=10, max_length=10)
    full_name: str = Field(..., min_length=1, max_length=200)

    @field_validator("pan_number")
    @classmethod
    def validate_pan_format(cls, value: str) -> str:
        value = value.upper()

        # Standard Indian PAN format: AAAAA9999A
        if not (
            len(value) == 10
            and value[:5].isalpha()
            and value[5:9].isdigit()
            and value[9].isalpha()
        ):
            raise ValueError("PAN must be in the format AAAAA9999A")

        return value


class PANVerificationResponse(BaseModel):
    id: str
    status: str
    verified_name: str | None
    name_match_result: str | None
    failure_reason: str | None


class KYCInitiateResponse(BaseModel):
    id: str
    status: str
    consent_url: str


class KYCStatusResponse(BaseModel):
    id: str
    status: str
    completed_at: datetime | None
    document_count: int
    failure_reason: str | None


class IdentityVerificationInitiateResponse(BaseModel):
    id: str
    status: str
    capture_session_token: str


class SubmitCaptureRequest(BaseModel):
    capture_ref: str = Field(..., min_length=1)


class IdentityVerificationResponse(BaseModel):
    id: str
    status: str
    confidence_score: float | None
    failure_reason: str | None


class OnboardingStatusResponse(BaseModel):
    mobile_verified: bool
    pan_status: str | None
    kyc_status: str | None
    identity_verification_status: str | None
    onboarding_complete: bool
