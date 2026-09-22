from uuid import uuid4

import pytest
import app.services.kyc_document as kyc_document_service
from app.services import document as document_service
from app.models.consent import Consent
from app.models.kyc_record import KYCRecord
from app.models.onboarding import OnboardingRecord
from app.providers.kyc import KYCStatusResult, KYCDocumentContent
from app.providers.storage import StoredDocument
from app.services.kyc_document import KYCDocumentService


class FakeKYCProvider:
    def __init__(self):
        self.fetch_count = 0

    async def get_status(self, provider_ref: str) -> KYCStatusResult:
        return KYCStatusResult(
            status="VERIFIED",
            available_document_refs=("provider-doc-1",),
        )

    async def fetch_document(self, provider_document_ref: str) -> KYCDocumentContent:
        self.fetch_count += 1
        return KYCDocumentContent(
            provider_document_ref=provider_document_ref,
            document_type="AADHAAR_XML",
            content=b"%PDF-1.7\nverified-document",
            content_type="application/pdf",
            )
class FakeStorage:
    def __init__(self):
        self.put_count = 0

    async def put(
        self,
        content: bytes,
        content_type: str,
        key_hint: str,
    ) -> StoredDocument:
        self.put_count += 1
        return StoredDocument(
            storage_ref="dev-storage-ref",
            checksum="a" * 64,
            size_bytes=len(content),
        )


@pytest.mark.asyncio
async def test_retrieve_kyc_documents_is_idempotent(db_session, user, monkeypatch):
    provider = FakeKYCProvider()
    storage = FakeStorage()

    monkeypatch.setattr(
        kyc_document_service,
        "get_kyc_provider",
        lambda: provider,
    )

    monkeypatch.setattr(
        document_service,
        "get_document_storage",
        lambda : storage,
    )

    onboarding = OnboardingRecord(
        user_id=user.id,
        status="IN_PROGRESS",
        current_step="KYC",
    )
    consent = Consent(
        user_id=user.id,
        consent_type="KYC",
        version="1.0",
        status="GRANTED",
    )
    db_session.add_all([onboarding, consent])
    await db_session.flush()

    kyc_record = KYCRecord(
        user_id=user.id,
        consent_id=consent.id,
        provider="development",
        provider_ref=f"kyc-{uuid4()}",
        kyc_type="DIGILOCKER",
        status="VERIFIED",
    )
    db_session.add(kyc_record)
    await db_session.flush()

    service = KYCDocumentService(db_session)

    first = await service.retrieve_documents(user_id=user.id)
    second = await service.retrieve_documents(user_id=user.id)

    assert len(first) == 1
    assert len(second) == 1
    assert first[0].id == second[0].id
    assert provider.fetch_count == 1
    assert storage.put_count == 1
@pytest.mark.asyncio
async def test_retrieve_kyc_documents_requires_verified_kyc(db_session, user):
    onboarding = OnboardingRecord(
        user_id=user.id,
        status="IN_PROGRESS",
        current_step="KYC",
    )
    consent = Consent(
        user_id=user.id,
        consent_type="KYC",
        version="1.0",
        status="GRANTED",
    )
    db_session.add_all([onboarding, consent])
    await db_session.flush()

    kyc_record = KYCRecord(
        user_id=user.id,
        consent_id=consent.id,
        provider="development",
        provider_ref=f"kyc-{uuid4()}",
        kyc_type="DIGILOCKER",
        status="PENDING",
    )
    db_session.add(kyc_record)
    await db_session.flush()

    service = KYCDocumentService(db_session)

    with pytest.raises(ValueError, match="only after verification"):
        await service.retrieve_documents(user_id=user.id)
