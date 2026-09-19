from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class IdentityVerificationSession:
    provider_ref: str
    capture_session_token: str


@dataclass(frozen=True)
class IdentityVerificationResult:
    status: str
    confidence_score: float | None = None
    failure_reason: str | None = None


class IdentityVerificationProvider(ABC):
    @abstractmethod
    async def start_session(self, user_id: str) -> IdentityVerificationSession:
        raise NotImplementedError

    @abstractmethod
    async def submit_capture(
        self,
        provider_ref: str,
        capture_ref: str,
    ) -> IdentityVerificationResult:
        raise NotImplementedError
