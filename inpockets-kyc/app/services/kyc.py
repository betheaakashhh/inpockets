import uuid
from datetime import UTC, datetime

from app.core.verification import document_storage, kyc_provider
from app.models.kyc_record import KYCRecord
from app.repositories.document import DocumentRepository
from app.repositories.kyc_document import KYCDocumentRepository
from app.repositories.kyc_record import KYCRecordRepository


class KYCService:
    def __init__(
        self,
        repository: KYCRecordRepository,
        kyc_document_repository: KYCDocumentRepository,
        document_repository: DocumentRepository,
    ):
        self.repository = repository
        self.kyc_document_repository = kyc_document_repository
        self.document_repository = document_repository

    async def initiate(
        self,
        *,
        user_id: uuid.UUID,
    ) -> tuple[KYCRecord, str]:
        """Returns (record, consent_url). consent_ref is a placeholder
        (str(uuid4)) standing in for a real consents-table entry - see the
        KYCRecord model docstring for why that table doesn't exist yet.
        """
        consent_ref = str(uuid.uuid4())

        result = await kyc_provider.initiate(
            user_id=str(user_id),
            consent_ref=consent_ref,
        )

        record = await self.repository.create(
            user_id=user_id,
            provider="mock",
            provider_ref=result.provider_ref,
            kyc_type="digilocker",
            consent_ref=consent_ref,
            initiated_at=datetime.now(UTC),
        )

        return record, result.consent_url

    async def refresh_status(self, *, record: KYCRecord) -> KYCRecord:
        """Polls the provider for the current status. On verified, retrieves
        and persists every available document through DocumentStorage - the
        one place raw KYC document bytes are ever written to our own
        storage, and it only happens once, not on every poll.
        """
        result = await kyc_provider.get_status(provider_ref=record.provider_ref)

        record.status = result.status
        record.failure_reason = result.failure_reason

        if record.status in ("verified", "failed", "manual_review"):
            record.completed_at = datetime.now(UTC)

        if record.status == "verified":
            for provider_document_ref in result.available_document_refs:
                content = await kyc_provider.fetch_document(
                    provider_document_ref=provider_document_ref,
                )

                stored = await document_storage.put(
                    content=content.content,
                    content_type=content.content_type,
                    key_hint=f"kyc_{record.id}",
                )

                document = await self.document_repository.create(
                    document_type="kyc_document",
                    owner_type="user",
                    owner_id=record.user_id,
                    storage_ref=stored.storage_ref,
                    checksum=stored.checksum,
                    content_type=content.content_type,
                    is_immutable=True,
                )

                await self.kyc_document_repository.create(
                    kyc_record_id=record.id,
                    document_id=document.id,
                    document_type=content.document_type,
                    retrieved_at=datetime.now(UTC),
                )

        return await self.repository.update(record)
