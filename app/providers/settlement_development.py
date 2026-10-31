"""Development settlement provider (never allowed in production).

Tests fill `reports` with the lines the "bank" would report and set
`behaviour` to simulate trouble:

  behaviour = "ok"         return the lines for (flow, date)
              "down"       raise SettlementUnavailable
              "malformed"  raise SettlementReportMalformed
"""

from __future__ import annotations

from datetime import date

from app.providers.settlement import (
    SettlementLine,
    SettlementProvider,
    SettlementReportMalformed,
    SettlementUnavailable,
)


class DevelopmentSettlementProvider(SettlementProvider):
    name = "development"

    behaviour: str = "ok"
    reports: dict[tuple[str, date], list[SettlementLine]] = {}
    fetch_calls: list[tuple[str, date]] = []

    @classmethod
    def reset(cls) -> None:
        cls.behaviour = "ok"
        cls.reports = {}
        cls.fetch_calls = []

    async def fetch_report(self, *, flow: str, report_date: date) -> list[SettlementLine]:
        self.fetch_calls.append((flow, report_date))
        if self.behaviour == "down":
            raise SettlementUnavailable("settlement report unavailable")
        if self.behaviour == "malformed":
            raise SettlementReportMalformed("settlement report unusable")
        return list(self.reports.get((flow, report_date), []))
