from __future__ import annotations 
from dataclasses import dataclass, field 
from enum import Enum 
from typing import Any 
class DecisionRoute(str, Enum): 
    """Backend-authoritative decision routes.""" 
    AUTO_APPROVED = "AUTO_APPROVED" 
    MANUAL_REVIEW = "MANUAL_REVIEW"
    AUTO_REJECTED = "AUTO_REJECTED"
    PENDING_ADDITIONAL_INFORMATION = "PENDING_ADDITIONAL_INFORMATION" 
    PENDING_EXTERNAL_PROVIDER = "PENDING_EXTERNAL_PROVIDER" 
    ERROR_REQUIRES_REVIEW = "ERROR_REQUIRES_REVIEW"

class DecisionReasonCode(str, Enum): 
    """Standard reasons retained with a decision route."""
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED" 
    ADDITIONAL_INFORMATION_REQUIRED = "ADDITIONAL_INFORMATION_REQUIRED"
    EXTERNAL_PROVIDER_REQUIRED = "EXTERNAL_PROVIDER_REQUIRED" 
    POLICY_REJECTED = "POLICY_REJECTED" 
    ASSESSMENT_ERROR = "ASSESSMENT_ERROR"
    
@dataclass(frozen=True)
class DecisionResult:
    """Immutable result of backend decision routing. This represents routing only. It does not authorize loan disbursement and does not replace lender-admin approval."""

    route: DecisionRoute
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    input_snapshot: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.route:
            raise ValueError("decision route is required")
        if not self.reason_codes and not self.reasons:
            raise ValueError("decision result must retain an explanation")
        if self.route == DecisionRoute.AUTO_APPROVED:
            raise ValueError(
                "AUTO_APPROVED is not permitted in the active lending flow"
            )