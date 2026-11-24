"""Kiểm thử tính ba yếu tố trên dữ liệu tổng hợp có đáp án tính tay."""
import pytest

from src.data import storage
from src.finance.factors import FactorConfig, compute_factors

# 8 phiên của thị trường; cửa sổ 5 phiên kết thúc ở D[7], ngày cơ sở là D[2]
D = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05",
     "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11"]
T = D[-1]
WIN = D[3:]          # D[3..7]
BASE = D[2]


def put(conn, sym, day, close, value, fb=0.0, fs=0.0):
    storage.upsert_daily(conn, [{
        "symbol": sym, "trading_date": day, "close": close, "total_match": 1000.0,
        "total_match_value": value, "foreign_buy_value": fb, "foreign_sell_value": fs}])


@pytest.fixture()
def conn(tmp_path):
    c = storage.connect(tmp_path / "f.db")
    storage.upsert_securities(c, [{"symbol": s, "board": "HOSE", "icb_code": "1", "listed_share": 1.0}
                                  for s in "ABCDEFG"])
    # Mã MKT giao dịch đủ 8 phiên để thiết lập lịch giao dịch thị trường
    for d in D:
        put(c, "MKT", d, 10000.0, 5e9)
    yield c
    c.close()


def by_symbol(items):
    return {it["symbol"]: it for it in items}


def test_calendar_and_window(conn):
    _, rep = compute_factors(conn)
    assert rep["as_of"] == T and rep["base_date"] == BASE
    assert rep["window_dates"] == WIN


def test_eligible_stock_exact_values(conn):
    closes = dict(zip(D, [100, 102, 110, 111, 112, 113, 114, 121]))   # giá D[2]=110, D[7]=121
    for d in D:
        put(conn, "A", d, float(closes[d]), 2e9, fb=3e8 if d in WIN else 0.0,
            fs=1e8 if d in WIN else 0.0)
    items, rep = compute_factors(conn)
    a = by_symbol(items)["A"]
    assert a["eligible"] and a["reason"] == "ok"
    assert a["momentum"] == pytest.approx(121 / 110 - 1)
    assert a["avg_value"] == pytest.approx(2e9)                      # (5 x 2e9) / 5
    assert a["foreign_ratio"] == pytest.approx(5 * (3e8 - 1e8) / (5 * 2e9))   # = 0.1
    assert a["traded_sessions"] == 5


def test_low_liquidity_excluded(conn):
    for d in D:
        put(conn, "B", d, 10000.0, 1e8)
    b = by_symbol(compute_factors(conn)[0])["B"]
    assert not b["eligible"] and b["reason"] == "thanh_khoan_thap"


def test_sparse_trading_counts_missing_sessions_as_zero(conn):
    # Chỉ giao dịch 2/5 phiên trong cửa sổ, mỗi phiên 3 tỷ => trung bình 5 phiên = 1,2 tỷ
    put(conn, "C", D[2], 10000.0, 3e9)
    put(conn, "C", WIN[1], 10000.0, 3e9)
    put(conn, "C", WIN[4], 10000.0, 3e9)
    c = by_symbol(compute_factors(conn)[0])["C"]
    assert c["avg_value"] == pytest.approx(1.2e9)
    assert c["traded_sessions"] == 2
    assert c["reason"] == "it_phien" and not c["eligible"]


def test_stopped_trading_in_window(conn):
    put(conn, "D", D[0], 10000.0, 9e9)           # chỉ có dữ liệu ở phiên đầu
    d = by_symbol(compute_factors(conn)[0])["D"]
    assert d["reason"] == "ngung_giao_dich" and not d["eligible"]


def test_price_jump_flagged_and_option_to_keep(conn):
    for d in D:
        put(conn, "E", d, 10000.0 if d < WIN[2] else 13000.0, 2e9)    # +30% giữa 2 phiên liền kề
    assert by_symbol(compute_factors(conn)[0])["E"]["reason"] == "gia_bat_thuong"
    cfg = FactorConfig(exclude_price_jumps=False)
    e = by_symbol(compute_factors(conn, cfg=cfg)[0])["E"]
    assert e["eligible"] and e["momentum"] == pytest.approx(0.3)


def test_no_history_before_base_date(conn):
    for d in WIN:                                # chỉ có dữ liệu trong cửa sổ
        put(conn, "F", d, 10000.0, 2e9)
    f = by_symbol(compute_factors(conn)[0])["F"]
    assert f["reason"] == "khong_du_lich_su" and f["momentum"] is None


def test_base_close_carried_forward(conn):
    put(conn, "G", D[1], 100.0, 2e9)             # không giao dịch đúng ngày cơ sở D[2]
    for d in WIN:
        put(conn, "G", d, 110.0, 2e9)
    g = by_symbol(compute_factors(conn)[0])["G"]
    assert g["eligible"] and g["momentum"] == pytest.approx(0.10)


def test_as_of_earlier_date_and_errors(conn):
    items, rep = compute_factors(conn, as_of=D[6])
    assert rep["as_of"] == D[6] and rep["base_date"] == D[1]
    with pytest.raises(ValueError):
        compute_factors(conn, as_of="2026-12-31")
    with pytest.raises(ValueError):
        compute_factors(conn, as_of=D[3])        # chưa đủ 5 phiên lịch sử

def test_boards_filter_limits_scope(conn):
    storage.upsert_securities(conn, [{"symbol": "H", "board": "HNX", "icb_code": "1", "listed_share": 1.0}])
    for d in D:
        put(conn, "A", d, 10000.0, 2e9)
        put(conn, "H", d, 10000.0, 2e9)
    everything = {it["symbol"] for it in compute_factors(conn)[0]}
    assert {"A", "H"} <= everything
    items, rep = compute_factors(conn, cfg=FactorConfig(boards=("HOSE",)))
    syms = {it["symbol"] for it in items}
    assert "A" in syms and "H" not in syms and "MKT" not in syms   # MKT chưa có thông tin sàn
    assert rep["boards"] == ["HOSE"]
    assert rep["as_of"] == T                                         # lịch giao dịch vẫn tính trên mọi mã