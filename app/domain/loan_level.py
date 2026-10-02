from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class LoanLevel:
    code: str
    name: str
    min_amount: Decimal
    max_amount: Decimal
    min_tenure_days: int
    max_tenure_days: int
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("loan level code is required")

        if not self.name.strip():
            raise ValueError("loan level name is required")

        if self.min_amount <= Decimal("0"):
            raise ValueError("min_amount must be greater than zero")

        if self.max_amount < self.min_amount:
            raise ValueError(
                "max_amount must be greater than or equal to min_amount"
            )

        if self.min_tenure_days <= 0:
            raise ValueError(
                "min_tenure_days must be greater than zero"
            )

        if self.max_tenure_days < self.min_tenure_days:
            raise ValueError(
                "max_tenure_days must be greater than or equal to "
                "min_tenure_days"
            )

    def supports_amount(self, amount: Decimal) -> bool:
        return self.min_amount <= amount <= self.max_amount

    def supports_tenure(self, tenure_days: int) -> bool:
        return self.min_tenure_days <= tenure_days <= self.max_tenure_days

    def supports(
        self,
        *,
        amount: Decimal,
        tenure_days: int,
    ) -> bool:
        return (
            self.supports_amount(amount)
            and self.supports_tenure(tenure_days)
        )