from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PANVerificationResult:
    provider_ref: str
    status: str
    verified_name: str | None = None
    name_match_result: str | None = None
    failure_reason: str | None = None


class PANProvider(ABC):
    @abstractmethod
    async def verify(
        self,
        pan_number: str,
        full_name: str,
    ) -> PANVerificationResult:
        raise NotImplementedError
