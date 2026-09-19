from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class IdentityVerificationSession:
    provider_ref: str
    capture_session_token: str


@dataclass
class IdentityVerificationResult:
    status: str  # "verified" | "failed" | "retry_required" | "manual_review"
    confidence_score: float | None = None
    failure_reason: str | None = None


class IdentityVerificationProvider(ABC):
    @abstractmethod
    async def start_session(
        self,
        user_id: str,
    ) -> IdentityVerificationSession:
        """Start a liveness/face-match capture session for a user."""
        raise NotImplementedError

    @abstractmethod
    async def submit_capture(
        self,
        provider_ref: str,
        capture_ref: str,
    ) -> IdentityVerificationResult:
        """Score a capture the client already uploaded, however the
        eventual vendor's SDK moves those bytes (this app does not assume
        that transport mechanism - see the module docstring in
        app/providers/mock_identity_verification.py).
        """
        raise NotImplementedError
