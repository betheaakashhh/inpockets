import uuid

from app.core.verification import identity_verification_provider
from app.models.identity_verification import IdentityVerification
from app.repositories.identity_verification import IdentityVerificationRepository


class IdentityVerificationService:
    def __init__(self, repository: IdentityVerificationRepository):
        self.repository = repository

    async def start_session(
        self,
        *,
        user_id: uuid.UUID,
    ) -> tuple[IdentityVerification, str]:
        """Returns (record, capture_session_token) - the client uses the
        token to drive whatever capture flow the eventual vendor's SDK
        requires. See app/providers/mock_identity_verification.py for why
        this app doesn't assume how the actual bytes move.
        """
        session = await identity_verification_provider.start_session(
            user_id=str(user_id),
        )

        record = await self.repository.create(
            user_id=user_id,
            provider="mock",
            provider_ref=session.provider_ref,
        )

        return record, session.capture_session_token

    async def submit_capture(
        self,
        *,
        record: IdentityVerification,
        capture_ref: str,
    ) -> IdentityVerification:
        result = await identity_verification_provider.submit_capture(
            provider_ref=record.provider_ref,
            capture_ref=capture_ref,
        )

        record.status = result.status
        record.confidence_score = result.confidence_score
        record.failure_reason = result.failure_reason

        return await self.repository.update(record)
