from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


from app.domain.kyc import KYCStatus
from app.providers.kyc import KYCProvider
from app.repositories.kyc_document import KYCDocumentRepository
from app.repositories.kyc_record import KYCRecordRepository
from app.services.kyc import get_kyc_provider
from app.services.document import DocumentService


class KYCDocumentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.provider: KYCProvider = get_kyc_provider()
        self.kyc_repository = KYCRecordRepository(session)
        self.kyc_document_repository = KYCDocumentRepository(session)
        self.document_service = DocumentService(session)

    async def retrieve_documents(self, *, user_id: UUID):
        record = await self.kyc_repository.get_latest_for_user(user_id=user_id)
        if record is None:
            raise ValueError("KYC has not been initiated")

        record = await self.kyc_repository.get_by_id_for_update(record.id)
        if record is None:
            raise ValueError("KYC record not found")

        if record.status != KYCStatus.VERIFIED.value:
            raise ValueError("KYC documents are available only after verification")

        status_result = await self.provider.get_status(record.provider_ref)
        if status_result.status != KYCStatus.VERIFIED.value:
            raise ValueError(
                f"KYC provider status is {status_result.status}; documents are not ready"
            )

        stored = []
        for provider_document_ref in status_result.available_document_refs:
            existing = await self.kyc_document_repository.get_by_provider_ref(
                kyc_record_id=record.id,
                provider_document_ref=provider_document_ref,
            )
            if existing is not None:
                stored.append(existing)
                continue

            content = await self.provider.fetch_document(provider_document_ref)
            if not content.content:
                raise ValueError(
                    f"KYC provider returned an empty document: {provider_document_ref}"
                )

            document = await self.document_service.store_document(
              owner_type="KYC_RECORD",
              owner_id=record.id,
              document_type=content.document_type,
              content=content.content,
              content_type=content.content_type,
              key_hint=f"kyc-{record.id}-{content.provider_document_ref}",
              immutable=True,
               )

            kyc_document = await self.kyc_document_repository.create(
                kyc_record_id=record.id,
                document_id=document.id,
                provider_document_ref=content.provider_document_ref,
                document_type=content.document_type,
                retrieved_at=datetime.now(timezone.utc),
            )
            stored.append(kyc_document)

        return stored
