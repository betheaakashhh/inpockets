import uuid

from app.core.verification import pan_provider
from app.models.pan_verification import PANVerification
from app.repositories.pan_verification import PANVerificationRepository


def mask_pan(pan_number: str) -> str:
    """ABCDE1234F -> ABCDE****F. Only the masked form is ever persisted -
    see the docstring on the PANVerification model for why.
    """
    if len(pan_number) <= 5:
        return "*" * len(pan_number)

    return pan_number[:5] + "*" * (len(pan_number) - 6) + pan_number[-1]


class PANVerificationService:
    def __init__(self, repository: PANVerificationRepository):
        self.repository = repository

    async def verify(
        self,
        *,
        user_id: uuid.UUID,
        pan_number: str,
        full_name: str,
    ) -> PANVerification:
        result = await pan_provider.verify(
            pan_number=pan_number,
            full_name=full_name,
        )

        return await self.repository.create(
            user_id=user_id,
            pan_number_masked=mask_pan(pan_number),
            provider="mock",
            provider_ref=result.provider_ref,
            status=result.status,
            verified_name=result.verified_name,
            name_match_result=result.name_match_result,
            failure_reason=result.failure_reason,
        )
