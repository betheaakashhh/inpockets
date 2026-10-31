"""2.14 matching rules (pure logic, no database)."""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.domain import reconciliation as r

D = Decimal
C, X = r.Flow.COLLECTION, r.Flow.DISBURSEMENT


def item(ref="p1", amount="100.00", status="SUCCESS", net=None, flow=C):
    return r.InternalItem(
        id=ref + "-id", ref=ref, amount=D(amount), status=status,
        ledger_net=D(net) if net is not None else r.expected_ledger_net(flow, status, D(amount)),
    )


def line(ref="p1", amount="100.00", status="SETTLED", line_id=None):
    return r.ExternalLine(line_id or f"L-{ref}", ref, D(amount), status)


def run(window, external, flow=C, lookup=None):
    lookup = lookup if lookup is not None else {i.ref: i for i in window}
    return r.reconcile(flow=flow, window_items=window, lookup=lookup, external=external)


def only(findings):
    assert len(findings) == 1
    return findings[0]


def test_perfect_match():
    f = only(run([item()], [line()]))
    assert (f.status, f.discrepancy) == (r.RecordStatus.MATCHED, None)


def test_perfect_match_for_a_payout_expects_money_out_of_the_bank():
    i = item(flow=X)
    assert i.ledger_net == D("-100.00")
    assert only(run([i], [line()], flow=X)).status == r.RecordStatus.MATCHED


def test_our_record_missing_from_the_provider_report():
    f = only(run([item()], []))
    assert (f.status, f.discrepancy) == (r.RecordStatus.UNMATCHED, r.Discrepancy.MISSING_EXTERNAL)
    assert f.external is None and f.external_count == 0


def test_provider_line_we_do_not_know():
    f = only(run([], [line("zzz")], lookup={}))
    assert (f.status, f.discrepancy) == (r.RecordStatus.UNMATCHED, r.Discrepancy.MISSING_INTERNAL)
    assert f.internal is None


def test_amount_mismatch():
    f = only(run([item()], [line(amount="99.00")]))
    assert (f.status, f.discrepancy) == (r.RecordStatus.MISMATCH, r.Discrepancy.AMOUNT_MISMATCH)


def test_a_one_paisa_difference_is_still_a_mismatch():
    f = only(run([item()], [line(amount="100.01")]))
    assert f.discrepancy == r.Discrepancy.AMOUNT_MISMATCH


def test_status_mismatch_when_provider_says_failed_but_we_say_success():
    f = only(run([item()], [line(status="FAILED")]))
    assert (f.status, f.discrepancy) == (r.RecordStatus.MISMATCH, r.Discrepancy.STATUS_MISMATCH)


def test_provider_settled_something_we_hold_as_pending_is_a_status_mismatch():
    pending = item(status="PENDING", net="0.00")
    f = only(run([], [line()], lookup={"p1": pending}))
    assert f.discrepancy == r.Discrepancy.STATUS_MISMATCH


def test_reversed_matches_reversed_and_expects_zero_net():
    rev = item(status="REVERSED")
    assert rev.ledger_net == D("0.00")
    assert only(run([rev], [line(status="REVERSED")])).status == r.RecordStatus.MATCHED


def test_failed_matches_failed():
    f = only(run([], [line(status="FAILED")], lookup={"p1": item(status="FAILED")}))
    assert f.status == r.RecordStatus.MATCHED


def test_duplicate_provider_line_is_counted_once_and_flagged():
    f = only(run([item()], [line(line_id="A"), line(line_id="B")]))
    assert (f.status, f.discrepancy) == (r.RecordStatus.REQUIRES_REVIEW, r.Discrepancy.DUPLICATE_EXTERNAL)
    assert f.external_count == 2


def test_exact_replay_of_the_same_line_is_also_flagged_not_hidden():
    f = only(run([item()], [line(line_id="A"), line(line_id="A")]))
    assert f.discrepancy == r.Discrepancy.DUPLICATE_EXTERNAL


def test_duplicate_for_an_unknown_reference_is_still_one_finding():
    f = only(run([], [line("q"), line("q", line_id="other")], lookup={}))
    assert f.discrepancy == r.Discrepancy.DUPLICATE_EXTERNAL and f.internal is None


def test_ledger_that_disagrees_with_the_payment_needs_review():
    f = only(run([item(net="0.00")], [line()]))
    assert (f.status, f.discrepancy) == (r.RecordStatus.REQUIRES_REVIEW, r.Discrepancy.LEDGER_MISMATCH)


def test_reversed_payment_whose_ledger_was_never_reversed_needs_review():
    f = only(run([item(status="REVERSED", net="100.00")], [line(status="REVERSED")]))
    assert f.discrepancy == r.Discrepancy.LEDGER_MISMATCH


def test_item_settled_on_another_day_is_found_by_reference_not_flagged_missing():
    outside = item()
    f = only(run([], [line()], lookup={"p1": outside}))
    assert f.status == r.RecordStatus.MATCHED


def test_one_finding_per_reference_across_a_mixed_batch():
    window = [item("a"), item("b"), item("c")]
    ext = [line("a"), line("b", amount="1.00"), line("z")]
    got = {f.provider_ref: f for f in run(window, ext, lookup={i.ref: i for i in window})}
    assert got["a"].status == r.RecordStatus.MATCHED
    assert got["b"].discrepancy == r.Discrepancy.AMOUNT_MISMATCH
    assert got["z"].discrepancy == r.Discrepancy.MISSING_INTERNAL
    assert got["c"].discrepancy == r.Discrepancy.MISSING_EXTERNAL
    assert r.summarize(list(got.values())) == {
        "matched": 1, "unmatched": 2, "mismatch": 1, "requires_review": 0,
    }


def test_day_window_is_an_indian_calendar_day():
    start, end = r.day_window(date(2026, 10, 20))
    assert start == datetime(2026, 10, 19, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 10, 20, 18, 30, tzinfo=UTC)
