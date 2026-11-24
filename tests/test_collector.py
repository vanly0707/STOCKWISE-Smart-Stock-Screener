"""Kiểm thử bộ lọc cổ phiếu, thu thập (chỉ HOSE), checkpoint và xử lý lỗi (dùng client giả)."""
import time
from datetime import timedelta

from src.data import collector, storage
from src.data.universe import get_universe, is_equity
from src.ssi_client.rest import SSIApiError, SSIClient, SSIRateLimitError

BOARDS = {
    "HOSE": [
        {"symbol": "ACB", "board": "HOSE", "icbCode": "8355", "listedShare": "5804421957"},
        {"symbol": "VCB", "board": "HOSE", "icbCode": "8355", "listedShare": "1"},
        {"symbol": "CACB2601", "board": "HOSE", "icbCode": "8355", "cwUnderlyingSymbol": "ACB"},
        {"symbol": "E1VFVN30", "board": "HOSE", "icbCode": "", "listedShare": "1"},
    ],
    "HNX": [
        {"symbol": "SHS", "board": "HNX", "icbCode": "8777"},
        {"symbol": "41B5GC000", "board": "DERIVATIVES", "icbCode": None},
    ],
    "UPCOM": [
        {"symbol": "A32", "board": "UPCOM", "icbCode": "3765", "listedShare": "6800000"},
    ],
}

INDEXES = {
    "VN30": [{"symbol": "ACB", "board": "HOSE"}, {"symbol": "SHS", "board": "HNX"}],
    "VN100": [{"symbol": "ACB", "board": "HOSE"},
              {"symbol": "HPG", "board": "HOSE", "icbCode": "1757"},   # HOSE nhưng danh sách sàn thiếu
              {"symbol": "VIC"},                                        # không ghi sàn
              {"symbol": "SHS", "board": "HNX"}],                       # sàn khác: phải bị loại
}


def _sessions():
    """Hai phiên gần nhất tính từ hôm nay, để test không phụ thuộc ngày chạy."""
    last = collector.last_expected_session(storage.now_vn().date())
    prev = collector.last_expected_session(last - timedelta(days=1))
    return prev.strftime("%Y/%m/%d"), last.strftime("%Y/%m/%d")


def _row(sym, d, close="10000"):
    return {"symbol": sym, "tradingDate": d, "close": close, "totalMatch": "1000",
            "totalMatchValue": "10000000", "totalForeignBuy": "10",
            "totalForeignBuyValue": "100000", "totalForeignSell": "20",
            "totalForeignSellValue": "200000"}


class FakeClient:
    def __init__(self, fail_on=None, quota_on=None):
        self.calls = []
        self.fail_on = fail_on or {}
        self.quota_on = quota_on

    def securities_list(self, *, board=None, index=None):
        if index:
            return INDEXES[index]
        return BOARDS[board]

    def securities_summary(self, symbol, start, end):
        self.calls.append(symbol)
        if symbol == self.quota_on:
            raise SSIRateLimitError("hết quota")
        if symbol in self.fail_on:
            raise self.fail_on[symbol]
        d1, d2 = _sessions()
        return [_row(symbol, d1), _row(symbol, d2)]


def _cfg(tmp_path):
    return {
        "universe": {"mode": "all", "boards": ["HOSE"], "include_indexes": []},
        "collect": {"db_path": str(tmp_path / "t.db"), "backfill_days": 60,
                    "overlap_days": 7, "min_interval": 0, "max_consecutive_errors": 10},
    }


def test_is_equity_filters_cw_etf_bonds():
    kept = [it["symbol"] for b in BOARDS.values() for it in b if is_equity(it)]
    assert kept == ["ACB", "VCB", "SHS", "A32"]


def test_universe_hose_only():
    syms = [r["symbol"] for r in get_universe(FakeClient(), {"mode": "all", "boards": ["HOSE"]})]
    assert syms == ["ACB", "VCB"]


def test_universe_multiple_boards_still_supported():
    syms = [r["symbol"] for r in get_universe(
        FakeClient(), {"mode": "all", "boards": ["HOSE", "HNX", "UPCOM"]})]
    assert syms == ["A32", "ACB", "SHS", "VCB"]


def test_universe_index_mode():
    idx = get_universe(FakeClient(), {"mode": "all", "boards": []}, index_override="VN30")
    assert [r["symbol"] for r in idx] == ["ACB", "SHS"]


def test_universe_adds_only_hose_index_members():
    cfg = {"mode": "all", "boards": ["HOSE"], "include_indexes": ["VN100"]}
    recs = {r["symbol"]: r for r in get_universe(FakeClient(), cfg)}
    assert sorted(recs) == ["ACB", "HPG", "VCB", "VIC"]      # SHS (HNX) bị loại
    assert recs["VIC"]["board"] == "HOSE"                    # mã không ghi sàn được gán HOSE


def test_collect_then_resume_skips_done(tmp_path):
    cfg = _cfg(tmp_path)
    res = collector.run(cfg, client=FakeClient())
    assert res["n_ok"] == 2 and res["n_rows"] == 4 and res["n_error"] == 0
    assert res["n_symbols"] == 2 and res["n_dates"] == 2
    assert res["note"] == "hoàn tất"
    c2 = FakeClient()
    res2 = collector.run(cfg, client=c2)
    assert c2.calls == [] and res2["n_skipped"] == 2
    c3 = FakeClient()
    collector.run(cfg, client=c3, force=True)
    assert sorted(c3.calls) == ["ACB", "VCB"]


def test_quota_stop_then_resume(tmp_path):
    cfg = _cfg(tmp_path)
    res = collector.run(cfg, client=FakeClient(quota_on="VCB"))   # thứ tự: ACB, VCB
    assert res["note"].startswith("dừng do quota")
    assert res["n_ok"] == 1                                       # chỉ ACB xong
    c2 = FakeClient()
    res2 = collector.run(cfg, client=c2)
    assert c2.calls == ["VCB"]                                    # không lấy lại ACB
    assert res2["n_ok"] == 1 and res2["n_skipped"] == 1


def test_error_on_one_symbol_does_not_stop_run(tmp_path):
    cfg = _cfg(tmp_path)
    res = collector.run(cfg, client=FakeClient(fail_on={"ACB": SSIApiError("HTTP 400")}))
    assert res["n_error"] == 1 and res["n_ok"] == 1
    conn = storage.connect(cfg["collect"]["db_path"])
    assert storage.get_status(conn, "ACB")["status"] == "error"
    assert storage.stats(conn)["n_symbols"] == 1


def test_upsert_is_idempotent(tmp_path):
    conn = storage.connect(tmp_path / "x.db")
    rows = [{"symbol": "ACB", "trading_date": "2026-11-09", "close": 1.0}]
    storage.upsert_daily(conn, rows)
    rows[0]["close"] = 2.0
    storage.upsert_daily(conn, rows)
    got = conn.execute("SELECT COUNT(*) c, MAX(close) m FROM daily_summary").fetchone()
    assert got["c"] == 1 and got["m"] == 2.0


def test_compute_start_uses_overlap():
    from datetime import date
    end = date(2026, 11, 22)
    assert collector.compute_start(None, end, 60, 7) == date(2026, 9, 23)
    st = {"last_trading_date": "2026-11-20"}
    assert collector.compute_start(st, end, 60, 7) == date(2026, 11, 13)


def test_quota_guard_waits_instead_of_stopping(monkeypatch):
    slept = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    c = SSIClient()
    c.remaining = 2
    c._check_quota()
    assert slept == [2.0] and c.remaining is None

    c.remaining, c._reset_at = 2, time.time() + 600
    try:
        c._check_quota()
        raise AssertionError("phải raise SSIRateLimitError")
    except SSIRateLimitError:
        pass

def test_last_expected_session_skips_weekend():
    from datetime import date
    assert collector.last_expected_session(date(2026, 11, 22)) == date(2026, 11, 20)  # CN
    assert collector.last_expected_session(date(2026, 11, 21)) == date(2026, 11, 20)  # T7
    assert collector.last_expected_session(date(2026, 11, 23)) == date(2026, 11, 23)  # T2


def _vn(y, m, d, hh, mm):
    from datetime import datetime
    return datetime(y, m, d, hh, mm, tzinfo=storage.VN_TZ)


def _st(last, collected, status="ok"):
    return {"status": status, "last_trading_date": last,
            "last_collected_at": collected.isoformat()}


def test_collected_today_basic_rules():
    now = _vn(2026, 11, 21, 10, 0)   # Thứ Bảy
    assert collector.collected_today(_st("2026-11-20", _vn(2026, 11, 21, 9, 0)), now.date(), now)
    assert not collector.collected_today(_st("2026-11-19", _vn(2026, 11, 21, 9, 0)), now.date(), now)
    assert not collector.collected_today(_st("2026-11-20", _vn(2026, 11, 21, 9, 0), "error"), now.date(), now)
    assert not collector.collected_today(None, now.date(), now)


def test_morning_run_skips_but_afternoon_refetches_intraday_data():
    # Thứ Hai 23/11: sáng đã có dữ liệu ngày 23 (lấy lúc 10:00)
    st = _st("2026-11-23", _vn(2026, 11, 23, 10, 0))
    assert collector.collected_today(st, _vn(2026, 11, 23, 11, 0).date(), _vn(2026, 11, 23, 11, 0))
    assert not collector.collected_today(st, _vn(2026, 11, 23, 16, 0).date(), _vn(2026, 11, 23, 16, 0))


def test_after_close_collection_is_skipped_on_next_run():
    st = _st("2026-11-23", _vn(2026, 11, 23, 16, 0))
    now = _vn(2026, 11, 23, 18, 0)
    assert collector.collected_today(st, now.date(), now)


def test_morning_without_todays_data_is_refetched_afternoon():
    st = _st("2026-11-20", _vn(2026, 11, 23, 9, 0))   # API sáng chỉ có đến 20/11
    assert not collector.collected_today(st, _vn(2026, 11, 23, 16, 0).date(), _vn(2026, 11, 23, 16, 0))


def test_weekend_run_after_friday_close_is_skipped_but_friday_midday_is_not():
    sat = _vn(2026, 11, 21, 10, 0)
    assert collector.collected_today(_st("2026-11-20", _vn(2026, 11, 20, 16, 0)), sat.date(), sat)
    assert not collector.collected_today(_st("2026-11-20", _vn(2026, 11, 20, 11, 0)), sat.date(), sat)