from __future__ import annotations
from typing import Any
from app.domain.decision import (
    DecisionReasonCode,
    DecisionResult,
    DecisionRoute,
)


class DecisionRouter:
    """Route policy/assessment outcomes to the backend decision state.

    This component only determines the authoritative route. It does not
    approve loans, create offers, or authorize disbursement.
    """

    def route(
        self,
        *,
        policy_route: DecisionRoute,
        reason_codes: tuple[str, ...] = (),
        reasons: tuple[str, ...] = (),
        input_snapshot: dict[str, Any] | None = None,
    ) -> DecisionResult:
        snapshot = dict(input_snapshot or {})

        # The active InPockets lending flow never automatically approves.
        if policy_route == DecisionRoute.AUTO_APPROVED:
            return DecisionResult(
                route=DecisionRoute.MANUAL_REVIEW,
                reason_codes=(
                    *reason_codes,
                    DecisionReasonCode.MANUAL_REVIEW_REQUIRED.value,
                ),
                reasons=(
                    *reasons,
                    "Lender admin review is required before approval.",
                ),
                input_snapshot=snapshot,
            )

        if policy_route == DecisionRoute.MANUAL_REVIEW:
            return DecisionResult(
                route=DecisionRoute.MANUAL_REVIEW,
                reason_codes=reason_codes
                or (DecisionReasonCode.MANUAL_REVIEW_REQUIRED.value,),
                reasons=reasons
                or ("Lender admin review is required.",),
                input_snapshot=snapshot,
            )

        if policy_route == DecisionRoute.AUTO_REJECTED:
            return DecisionResult(
                route=DecisionRoute.AUTO_REJECTED,
                reason_codes=reason_codes
                or (DecisionReasonCode.POLICY_REJECTED.value,),
                reasons=reasons
                or ("Policy conditions require rejection.",),
                input_snapshot=snapshot,
            )

        if policy_route == DecisionRoute.PENDING_ADDITIONAL_INFORMATION:
            return DecisionResult(
                route=DecisionRoute.PENDING_ADDITIONAL_INFORMATION,
                reason_codes=reason_codes
                or (
                    DecisionReasonCode.ADDITIONAL_INFORMATION_REQUIRED.value,
                ),
                reasons=reasons
                or ("Additional information is required.",),
                input_snapshot=snapshot,
            )

        if policy_route == DecisionRoute.PENDING_EXTERNAL_PROVIDER:
            return DecisionResult(
                route=DecisionRoute.PENDING_EXTERNAL_PROVIDER,
                reason_codes=reason_codes
                or (DecisionReasonCode.EXTERNAL_PROVIDER_REQUIRED.value,),
                reasons=reasons
                or ("An external provider result is required.",),
                input_snapshot=snapshot,
            )

        if policy_route == DecisionRoute.ERROR_REQUIRES_REVIEW:
            return DecisionResult(
                route=DecisionRoute.ERROR_REQUIRES_REVIEW,
                reason_codes=reason_codes
                or (DecisionReasonCode.ASSESSMENT_ERROR.value,),
                reasons=reasons
                or ("The assessment requires manual review.",),
                input_snapshot=snapshot,
            )

        raise ValueError(f"unsupported decision route: {policy_route}")
