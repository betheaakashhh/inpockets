from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class KYCInitiationResult:
    provider_ref: str
    consent_url: str


@dataclass
class KYCDocumentContent:
    provider_document_ref: str
    document_type: str
    content: bytes
    content_type: str


@dataclass
class KYCStatusResult:
    status: str  # "pending" | "verified" | "failed" | "manual_review"
    available_document_refs: tuple[str, ...] = ()
    failure_reason: str | None = None


class KYCProvider(ABC):
    @abstractmethod
    async def initiate(
        self,
        user_id: str,
        consent_ref: str,
    ) -> KYCInitiationResult:
        """Start a KYC consent flow (e.g. DigiLocker) for a user."""
        raise NotImplementedError

    @abstractmethod
    async def get_status(
        self,
        provider_ref: str,
    ) -> KYCStatusResult:
        """Poll the provider for the current status of a KYC attempt."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_document(
        self,
        provider_document_ref: str,
    ) -> KYCDocumentContent:
        """Fetch raw bytes for one document made available after VERIFIED.

        The provider never touches our database directly - this method
        returns raw content, and the caller (KYCService) is responsible for
        persisting it through DocumentStorage. That boundary is what keeps
        provider adapters swappable without touching storage logic.
        """
        raise NotImplementedError
