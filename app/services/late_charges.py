from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain import late_charges as dom
from app.domain.pricing import LateTerms
from app.domain.repayment import today_ist
from app.repositories.late_charge import LateChargeRepository
from app.repositories.pricing import PricingRepository
from app.repositories.repayment import RepaymentRepository
from app.services.pricing import late_of

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssessResult:
    charges: int
    total: Decimal


class LateChargeService:
    """Assesses KreditBee-style late charges on overdue installments.

    Safe to run any number of times and from several workers: it locks the
    schedule first (the same order every payment uses), skips days already
    charged (unique per installment and day) and only ever ADDS to an
    installment's fee_due. A loan whose offer did not switch late charges on
    is never touched."""

    def __init__(self, *, session, audit_log_service):
        self.session = session
        self.audit = audit_log_service
        self.repository = LateChargeRepository(session)
        self.schedules = RepaymentRepository(session)
        self.pricing = PricingRepository(session)

    async def candidates(self, *, limit: int = 200, today: date | None = None):
        return await self.repository.schedules_with_overdue(today=today or today_ist(), limit=limit)

    async def assess_schedule(self, schedule_id, *, today: date | None = None) -> AssessResult:
        today = today or today_ist()
        schedule = await self.schedules.get_schedule(schedule_id, for_update=True)
        if schedule is None or schedule.status != "ACTIVE":
            return AssessResult(0, Decimal("0.00"))
        snapshot = await self.pricing.get_snapshot(schedule.loan_offer_id)
        if snapshot is None:
            return AssessResult(0, Decimal("0.00"))
        terms: LateTerms = late_of(snapshot)
        if not terms.enabled:
            return AssessResult(0, Decimal("0.00"))

        count, total = 0, Decimal("0.00")
        for inst in await self.schedules.list_installments(schedule.id, for_update=True):
            if inst.due_date >= today or inst.principal_due - inst.principal_paid <= 0:
                continue
            charged, last = await self.repository.charged_so_far(inst.id)
            for day in dom.days_to_assess(inst.due_date, last, today, terms):
                overdue = inst.principal_due - inst.principal_paid
                charge = dom.charge_for_day(
                    due_date=inst.due_date,
                    on=day,
                    overdue_principal=overdue,
                    already_charged=charged,
                    principal_due=inst.principal_due,
                    interest_due=inst.interest_due,
                    terms=terms,
                )
                if charge is None:
                    continue
                inserted = await self.repository.add(
                    installment_id=inst.id,
                    schedule_id=schedule.id,
                    loan_offer_id=schedule.loan_offer_id,
                    kind=charge.kind,
                    charge_date=charge.charge_date,
                    basis_amount=charge.basis,
                    amount=charge.amount,
                )
                if not inserted:
                    continue
                inst.fee_due += charge.amount
                charged += charge.amount
                count += 1
                total += charge.amount
        if count:
            await self.session.flush()
            await self.audit.record_system_action(
                action="LATE_CHARGES_ASSESSED",
                entity_type="repayment_schedule",
                entity_id=str(schedule.id),
                new_value={"charges": count, "total": str(total), "through": today.isoformat()},
                event_metadata={"loan_offer_id": str(schedule.loan_offer_id)},
            )
        return AssessResult(count, total)
