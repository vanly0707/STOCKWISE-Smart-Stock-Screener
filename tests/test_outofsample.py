"""Kiểm thử kiểm tra ngoài mẫu bằng dữ liệu tổng hợp có đáp án biết trước."""
import random
from datetime import date, timedelta

from src.data import storage
from src.finance.factors import FactorConfig
from src.finance.outofsample import forward_return, run_oos, summarize


def _dates(n):
    d, out = date(2026, 1, 5), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _build(tmp_path, n_sym=40, n_days=40, predictive=True, jump_sym=None, seed=1):
    """Mã có thanh khoản cao hơn thì LUÔN tăng giá nhanh hơn sau đó (predictive) hoặc ngẫu nhiên."""
    rng = random.Random(seed)
    conn = storage.connect(tmp_path / "o.db")
    rows = []
    for k in range(n_sym):
        price, value = 10000.0, 1e9 * (k + 1)
        drift = 0.0005 * (k - n_sym / 2) if predictive else rng.uniform(-0.01, 0.01)
        for j, d in enumerate(_dates(n_days)):
            price *= 1 + drift + (0 if predictive else rng.uniform(-0.01, 0.01))
            if jump_sym == k and j == 30:
                price *= 1.5
            rows.append({"symbol": f"S{k:02d}", "trading_date": d, "close": price,
                         "total_match_value": value, "foreign_buy_value": 0.0,
                         "foreign_sell_value": 0.0})
    storage.upsert_daily(conn, rows)
    return conn


CFG = FactorConfig(window=5, min_avg_value=0.0, min_traded_sessions=4, max_daily_move=0.2)


def test_predictive_liquidity_gives_positive_ic(tmp_path):
    conn = _build(tmp_path, predictive=True)
    res = run_oos(conn, h=5, cfg=CFG)
    assert res["n_dates"] >= 3
    assert res["summary"]["ic_score_liquidity"]["mean"] > 0.9   # thanh khoản xếp đúng thứ tự tăng giá


def test_no_lookahead_future_data_does_not_change_past_score(tmp_path):
    conn = _build(tmp_path, predictive=False)
    a = run_oos(conn, h=5, cfg=CFG)["days"][0]
    # đổi toàn bộ giá SAU ngày kết thúc cửa sổ lợi suất đầu tiên: IC ngày đầu phải giữ nguyên
    conn.execute("UPDATE daily_summary SET close = close * 7 WHERE trading_date > ?", (a["end"],))
    conn.commit()
    b = run_oos(conn, h=5, cfg=CFG)["days"][0]
    assert a["ic"] == b["ic"] and a["spread"] == b["spread"]


def test_price_jump_in_forward_window_is_dropped(tmp_path):
    conn = _build(tmp_path, jump_sym=5, predictive=True)
    with_f = run_oos(conn, h=5, cfg=CFG, step=1)
    no_f = run_oos(conn, h=5, cfg=CFG, step=1, drop_jumps=False)
    hit = [d for d in with_f["days"] if d["n_dropped"] > 0]
    assert hit and all(d["n_dropped"] == 0 for d in no_f["days"])


def test_forward_return_basic_and_missing():
    s = (["2026-01-05", "2026-01-06", "2026-01-08"], [100.0, 110.0, 121.0])
    pos = {"2026-01-05": 0, "2026-01-06": 1, "2026-01-07": 2, "2026-01-08": 3}
    assert abs(forward_return(s, "2026-01-05", "2026-01-08", pos, None) - 0.21) < 1e-12
    assert forward_return(s, "2026-01-07", "2026-01-08", pos, None) is None   # không có giá tại t
    assert forward_return(s, "2026-01-08", "2026-01-08", pos, None) is None   # không có giá mới hơn
    assert forward_return(s, "2026-01-05", "2026-01-06", pos, 0.07) is None   # +10% > ngưỡng 7%


def test_summarize():
    s = summarize([0.1, 0.3, None, -0.1])
    assert s["n"] == 3 and abs(s["mean"] - 0.1) < 1e-12 and abs(s["hit"] - 2 / 3) < 1e-12
    assert summarize([None])["n"] == 0


def test_too_few_sessions_returns_empty(tmp_path):
    conn = _build(tmp_path, n_days=8)
    assert run_oos(conn, h=5, cfg=CFG)["n_dates"] == 0