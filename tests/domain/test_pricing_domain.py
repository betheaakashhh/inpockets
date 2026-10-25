from datetime import date
from decimal import Decimal as D

import pytest

from app.domain import pricing as P

START = date(2026, 1, 1)
T36 = P.PricingTerms(D("36"), D("6"), D("18"))


def test_fee_gst_and_net_payout_example():
    fee, gst = P.fee_and_gst(D("5000"), T36)
    assert (fee, gst) == (D("300.00"), D("54.00"))
    qt = P.quote(principal=D("5000"), tenure_days=90, terms=T36, start=START)
    assert qt.net_payout == D("4646.00")
    assert qt.months == 3


def test_gst_applies_to_the_fee_only_never_to_principal_or_interest():
    zero_fee = P.PricingTerms(D("36"), D("0"), D("18"))
    qt = P.quote(principal=D("5000"), tenure_days=90, terms=zero_fee, start=START)
    assert qt.gst == 0 and qt.net_payout == D("5000.00")


def test_three_month_emi_example_at_36_percent():
    qt = P.quote(principal=D("5000"), tenure_days=90, terms=T36, start=START)
    assert qt.emi == D("1767.65")
    assert qt.total_interest == D("302.96")
    assert qt.total_repayable == D("5302.96")
    assert D("82.9") < qt.apr_percent < D("83.1")


def test_apr_counts_the_fee_so_it_exceeds_the_interest_rate():
    no_fee = P.quote(principal=D("5000"), tenure_days=90, terms=P.PricingTerms(D("36"), D("0"), D("18")), start=START)
    with_fee = P.quote(principal=D("5000"), tenure_days=90, terms=T36, start=START)
    assert no_fee.apr_percent == D("36.00")
    assert with_fee.apr_percent > no_fee.apr_percent


def test_schedule_rows_follow_a_reducing_balance():
    rows = P.emi_schedule(principal=D("5000"), annual_interest_percent=D("36"), months=3, start=START)
    assert [r.interest for r in rows] == [D("150.00"), D("101.47"), D("51.49")]
    assert [r.principal for r in rows] == [D("1617.65"), D("1666.18"), D("1716.17")]
    assert [r.due_date for r in rows] == [date(2026, 1, 31), date(2026, 3, 2), date(2026, 4, 1)]


@pytest.mark.parametrize("principal", ["1000", "5000", "7777.77", "12345.67", "50000"])
@pytest.mark.parametrize("months", [1, 2, 3, 6, 12, 24, 60])
@pytest.mark.parametrize("rate", ["0", "12", "24", "36"])
def test_principal_always_sums_exactly_and_every_row_is_positive(principal, months, rate):
    rows = P.emi_schedule(
        principal=D(principal), annual_interest_percent=D(rate), months=months, start=START
    )
    assert sum((r.principal for r in rows), D(0)) == D(principal).quantize(D("0.01"))
    assert all(r.principal > 0 and r.interest >= 0 for r in rows)
    # equal instalments except the last, which absorbs rounding (a few paise)
    assert abs(rows[-1].total - rows[0].total) < D("1.00")


def test_zero_interest_splits_principal_evenly():
    rows = P.emi_schedule(principal=D("1000"), annual_interest_percent=D("0"), months=3, start=START)
    assert all(r.interest == 0 for r in rows)
    assert [r.principal for r in rows] == [D("333.33"), D("333.33"), D("333.34")]
    assert P.quote(principal=D("1000"), tenure_days=90, terms=P.PricingTerms(D("0"), D("0"), D("18")), start=START).apr_percent == D("0.00")


def test_tenure_must_be_whole_thirty_day_months():
    for bad in (0, 15, 29, 31, 45, 100, 30 * 61):
        with pytest.raises(P.PricingError):
            P.months_for_tenure(bad)
    assert P.months_for_tenure(30) == 1 and P.months_for_tenure(180) == 6


def test_terms_are_range_checked():
    for bad in (
        P.PricingTerms(D("-1"), D("5"), D("18")),
        P.PricingTerms(D("101"), D("5"), D("18")),
        P.PricingTerms(D("30"), D("26"), D("18")),
        P.PricingTerms(D("30"), D("5"), D("51")),
    ):
        with pytest.raises(P.PricingError):
            bad.validate()


def test_even_the_largest_allowed_fee_and_gst_leave_a_positive_payout():
    qt = P.quote(principal=D("1000"), tenure_days=30, terms=P.PricingTerms(D("30"), D("25"), D("50")), start=START)
    assert qt.net_payout == D("625.00") and qt.processing_fee + qt.gst == D("375.00")


def test_display_terms_are_plain_strings_and_cover_every_system_key():
    qt = P.quote(principal=D("5000"), tenure_days=90, terms=T36, start=START)
    late = P.LateTerms(False, D("4"), D("500"), D("36"), 180, D("40"))
    shown = P.display_terms(version=3, terms=T36, late=late, qt=qt)
    assert set(shown) == P.SYSTEM_TERM_KEYS
    assert all(isinstance(v, str) for v in shown.values())
    assert shown["net_disbursal_amount"] == "4646.00" and shown["emi_amount"] == "1767.65"
    assert shown["interest_rate_percent_per_annum"] == "36" and shown["processing_fee_percent"] == "6"
    assert "No late" in shown["late_payment_charges"]


def test_late_description_matches_the_kreditbee_format_when_enabled():
    late = P.LateTerms(True, D("4"), D("500"), D("36"), 180, D("40"))
    text = late.describe()
    assert "lower of 4% of the overdue principal or Rs 500.00" in text
    assert "36% a year" in text and "180 days" in text and "40%" in text
