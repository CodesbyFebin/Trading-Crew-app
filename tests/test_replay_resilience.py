from decimal import Decimal as D

from crew.desk_d4 import Tick, s09_dataqa
from crew.orderbook import StalenessGuard


def _tick(ts, bid="100", ask="101", status="TRADING"):
    return Tick(ts, "BTCUSDT", D(bid), D(ask), ((D(bid), D("2")),),
                ((D(ask), D("2")),), D("100000"), status)


def test_replay_chaos_deduplicates_and_rejects_bad_order_book_and_clock_rows():
    report = s09_dataqa([
        _tick(1000),
        _tick(1000),                  # duplicate
        _tick(990),                   # reordered
        _tick(1060, "102", "101"),   # crossed book
        _tick(1120, status="HALTED"),
        _tick(1400),                  # gap after last accepted row
    ])
    assert (report.input_rows, report.duplicates, report.out_of_order) == (6, 1, 1)
    assert (report.crossed, report.non_trading, report.gaps) == (1, 1, 1)
    assert [t.ts for t in report.ticks] == [1000, 1400]

    guard = StalenessGuard(max_gap_s=120)
    assert guard.check("BTCUSDT", 1000) == (True, "OK")
    assert guard.check("BTCUSDT", 1400) == (False, "STALE")
    assert guard.blocked == {"STALE": 1}
