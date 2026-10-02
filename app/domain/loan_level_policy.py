from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.loan_level import LoanLevel


@dataclass(frozen=True)
class LoanLevelConstraintResult:
    loan_level_code: str
    amount_valid: bool
    tenure_valid: bool

    @property
    def valid(self) -> bool:
        return self.amount_valid and self.tenure_valid


class LoanLevelPolicyConstraint:
    """Validate an application against its configured loan level.

    This is a policy constraint, not a risk score.
    """

    def validate(
        self,
        *,
        loan_level: LoanLevel,
        requested_amount: Decimal,
        requested_tenure_days: int,
    ) -> LoanLevelConstraintResult:
        return LoanLevelConstraintResult(
            loan_level_code=loan_level.code,
            amount_valid=loan_level.supports_amount(
                requested_amount
            ),
            tenure_valid=loan_level.supports_tenure(
                requested_tenure_days
            ),
        )