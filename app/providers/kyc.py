from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class KYCInitiationResult:
    provider_ref: str
    consent_url: str


@dataclass(frozen=True)
class KYCDocumentContent:
    provider_document_ref: str
    document_type: str
    content: bytes
    content_type: str


@dataclass(frozen=True)
class KYCStatusResult:
    status: str
    available_document_refs: tuple[str, ...] = ()
    failure_reason: str | None = None


class KYCProvider(ABC):
    @abstractmethod
    async def initiate(
        self,
        user_id: str,
        consent_ref: str,
    ) -> KYCInitiationResult:
        raise NotImplementedError

    @abstractmethod
    async def get_status(self, provider_ref: str) -> KYCStatusResult:
        raise NotImplementedError

    @abstractmethod
    async def fetch_document(
        self,
        provider_document_ref: str,
    ) -> KYCDocumentContent:
        raise NotImplementedError
