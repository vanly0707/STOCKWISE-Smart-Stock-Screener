"""Kiểm thử lớp dịch vụ của giao diện (không cần Streamlit/Plotly)."""
from datetime import date

import pytest

from src.app import services
from src.data import storage
from src.finance.factors import FactorConfig

D = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05",
     "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11"]
FC = FactorConfig(window=5, min_avg_value=1e9, min_traded_sessions=4, boards=("HOSE",))


def put(conn, sym, day, close, value, fb=0.0, fs=0.0):
    storage.upsert_daily(conn, [{"symbol": sym, "trading_date": day, "close": close,
                                 "total_match": 1000.0, "total_match_value": value,
                                 "foreign_buy_value": fb, "foreign_sell_value": fs}])


@pytest.fixture()
def conn(tmp_path):
    c = storage.connect(tmp_path / "a.db")
    storage.upsert_securities(c, [{"symbol": s, "board": "HOSE", "icb_code": "1", "listed_share": 1.0}
                                  for s in ("AAA", "BBB", "CCC", "DDD")])
    # AAA: tăng, thanh khoản lớn, khối ngoại mua; BBB: đi ngang; CCC: giảm, bán ròng; DDD: thanh khoản thấp
    for i, d in enumerate(D):
        put(c, "AAA", d, 10000.0 + 300 * i, 9e9, fb=2e9, fs=1e9)
        put(c, "BBB", d, 20000.0, 5e9)
        put(c, "CCC", d, 30000.0 - 200 * i, 3e9, fb=0.5e9, fs=1.5e9)
        put(c, "DDD", d, 5000.0, 1e8)
    storage.finish_run(c, storage.start_run(c), n_symbols=4, n_ok=4, n_skipped=0,
                       n_error=0, n_rows=32, note="hoàn tất")
    yield c
    c.close()


def test_status_ok_stale_error_and_unfinished(conn, tmp_path):
    ok = services.get_status(conn, today=date(2026, 11, 12))
    assert ok.level == "ok" and ok.last_date == "2026-11-11" and ok.n_sessions == 8
    assert services.get_status(conn, today=date(2026, 11, 20)).level == "warn"
    empty = storage.connect(tmp_path / "empty.db")
    assert services.get_status(empty, today=date(2026, 11, 12)).level == "error"
    storage.finish_run(conn, storage.start_run(conn), n_symbols=4, n_ok=1, n_skipped=0,
                       n_error=0, n_rows=1, note="dừng do quota: hết")
    s = services.get_status(conn, today=date(2026, 11, 12))
    assert s.level == "warn" and "quota" in s.message


def test_weights_parsing():
    assert services.parse_weights("equal")[1] is None
    w, err = services.parse_weights("custom", 50, 30, 20)
    assert err is None and w == pytest.approx((0.5, 0.3, 0.2))
    w, err = services.parse_weights("custom", 50, 30, 30)
    assert w is None and "110" in err


def test_make_factor_config_scales_sessions():
    assert services.make_factor_config(FC, 5, 1e9).min_traded_sessions == 4
    assert services.make_factor_config(FC, 10, 2e9).min_traded_sessions == 8
    assert services.make_factor_config(FC, 20, 5e8).min_avg_value == 5e8


def test_ranking_metrics_and_table(conn):
    items, rep, rows = services.build_ranking(conn, FC, services.EQUAL_WEIGHTS)
    assert [r["symbol"] for r in rows][0] == "AAA"            # mạnh nhất cả ba yếu tố
    assert "DDD" not in {r["symbol"] for r in rows}            # thanh khoản dưới ngưỡng
    m = services.summary_metrics(items, rows)
    assert m["n_total"] == 4 and m["n_eligible"] == 3
    assert m["pct_positive_momentum"] == pytest.approx(100 / 3)   # chỉ AAA tăng
    assert m["avg_value_total_bn"] == pytest.approx(9 + 5 + 3)
    assert m["net_foreign_bn"] == pytest.approx((1 + 0 - 1) )     # AAA +1, CCC -1 tỷ/phiên
    assert services.rows_to_table(rows, "aa")[0]["Mã"] == "AAA"
    assert services.rows_to_table(rows, "ZZZ") == []
    assert len(services.rows_to_table(rows, top=2)) == 2
    assert services.reason_counts(items)["Thanh khoản dưới ngưỡng"] == 1
    assert services.excluded_table(items)[0]["Mã"] == "DDD"


def test_contributions_sum_to_score(conn):
    _, _, rows = services.build_ranking(conn, FC, services.EQUAL_WEIGHTS)
    c = services.contributions(rows, services.EQUAL_WEIGHTS, top=3)
    first = c[0]
    assert sum(first[k] for k in services.FACTOR_LABELS.values()) == pytest.approx(rows[0]["score"])


def test_price_history_and_explain(conn):
    h = services.price_history(conn, "AAA", limit=5)
    assert len(h) == 5 and h[0]["date"] < h[-1]["date"]
    assert h[-1]["foreign_net_bn"] == pytest.approx(1.0) and h[-1]["value_bn"] == pytest.approx(9.0)
    _, _, rows = services.build_ranking(conn, FC, services.EQUAL_WEIGHTS)
    text = services.explain(rows[0], len(rows))
    assert "AAA xếp hạng 1/3" in text and "không phải dự báo lợi nhuận" in text


def test_dates_and_max_window(conn):
    dates = services.available_dates(conn)
    assert dates[0] == D[-1] and dates[-1] == D[0]
    assert services.max_window(conn, D[-1]) == 7
    assert services.max_window(conn, D[2]) == 2     # chưa đủ cho cửa sổ 5
    assert services.max_window(conn, "1999-01-01") == 0
