from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


class PolicyRuleEffect(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_MANUAL_REVIEW = "REQUIRE_MANUAL_REVIEW"
    REQUIRE_ADDITIONAL_INFORMATION = "REQUIRE_ADDITIONAL_INFORMATION"
    REQUIRE_EXTERNAL_PROVIDER = "REQUIRE_EXTERNAL_PROVIDER"
    REJECT = "REJECT"


class DecisionRoute(str, Enum):
    AUTO_APPROVED = "AUTO_APPROVED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    AUTO_REJECTED = "AUTO_REJECTED"
    PENDING_ADDITIONAL_INFORMATION = "PENDING_ADDITIONAL_INFORMATION"
    PENDING_EXTERNAL_PROVIDER = "PENDING_EXTERNAL_PROVIDER"
    ERROR_REQUIRES_REVIEW = "ERROR_REQUIRES_REVIEW"


@dataclass(frozen=True)
class PolicyRule:
    """
    Versioned lending-policy rule.

    Rules are evaluated in explicit order. The policy engine interprets
    these rules; the Risk Engine remains responsible only for risk
    assessment.
    """

    code: str
    order: int
    effect: PolicyRuleEffect
    condition: dict[str, Any] = field(default_factory=dict)
    reason_code: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("rule code is required")

        if self.order < 0:
            raise ValueError("rule order must be non-negative")


@dataclass(frozen=True)
class PolicyVersion:
    """
    Immutable version of the lending policy.

    A policy version becomes historical once it has been used for an
    evaluation. New policy changes must create a new version rather
    than modifying the historical one.
    """

    version: str
    rules: tuple[PolicyRule, ...]
    effective_from: datetime
    effective_to: datetime | None = None

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("policy version is required")

        if not self.rules:
            raise ValueError("policy version must contain at least one rule")

        if (
            self.effective_to is not None
            and self.effective_to <= self.effective_from
        ):
            raise ValueError(
                "effective_to must be later than effective_from"
            )


@dataclass(frozen=True)
class PolicyEvaluation:
    """
    Immutable historical record of evaluating one application against
    one exact policy version.
    """

    id: UUID
    user_id: UUID
    loan_application_id: UUID
    policy_version: str
    evaluated_at: datetime
    decision_route: DecisionRoute
    matched_rule_codes: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    input_snapshot: dict[str, Any] = field(default_factory=dict)
    recommended_amount: Decimal | None = None
    max_eligible_amount: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy version is required")

        if not self.matched_rule_codes and not self.reasons:
            raise ValueError(
                "policy evaluation must retain an explanation"
            )