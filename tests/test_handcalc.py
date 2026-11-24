"""Đối chiếu tính tay (cửa sổ 2 phiên, 3 mã): mọi số ở đây được tính bằng tay trong báo cáo.

Phiên: d0=16/11, d1=17/11 (ngày cơ sở), d2=18/11, d3=19/11 (ngày đánh giá). Đơn vị giá trị: đồng.
  A: close 100,100,100,110 | GT khớp 10,10,10,10 | NN mua d2,d3 = 4,2; bán = 1,1
  B: close  50, 50, 55, 44 | GT khớp 20,20,20,20 | NN mua 0,0;  bán = 10,10
  C: close  20, 20, 20, 21 | GT khớp  5, 5, 5,15 | khối ngoại 0
  D: chỉ giao dịch d0, d1 (không có trong cửa sổ)
Động lượng: A=110/100-1=+10%, B=44/50-1=-12%, C=21/20-1=+5%
Thanh khoản (TB/phiên): A=(10+10)/2=10, B=20, C=(5+15)/2=10
Khối ngoại: A=(6-2)/20=+0.2, B=(0-20)/40=-0.5, C=0
Điểm thành phần (xếp hạng phần trăm, 3 mã -> 0/50/100; đồng hạng lấy hạng TB):
  động lượng A=100,C=50,B=0; thanh khoản B=100, A=C=25; khối ngoại A=100,C=50,B=0
Điểm tổng bằng nhau: A=(100+25+100)/3=75, C=(50+25+50)/3=41.667, B=(0+100+0)/3=33.333
Điểm tổng 50/30/20:  A=50+7.5+20=77.5, C=25+7.5+10=42.5, B=0+30+0=30
"""
import pytest

from src.data import storage
from src.finance.factors import FactorConfig, compute_factors
from src.finance.scoring import (EQUAL_WEIGHTS, component_scores, rank_with_weights,
                                 weights_from_percent)

D = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"]


def _rows():
    spec = {
        "A": ([100, 100, 100, 110], [10, 10, 10, 10], [0, 0, 4, 2], [0, 0, 1, 1]),
        "B": ([50, 50, 55, 44], [20] * 4, [0] * 4, [0, 0, 10, 10]),
        "C": ([20, 20, 20, 21], [5, 5, 5, 15], [0] * 4, [0] * 4),
        "D": ([30, 30], [10, 10], [0, 0], [0, 0]),
    }
    out = []
    for sym, (close, val, fb, fs) in spec.items():
        for k in range(len(close)):
            out.append({"symbol": sym, "trading_date": D[k], "close": float(close[k]),
                        "total_match_value": float(val[k]),
                        "foreign_buy_value": float(fb[k]), "foreign_sell_value": float(fs[k])})
    return out


@pytest.fixture()
def ranked(tmp_path):
    conn = storage.connect(tmp_path / "h.db")
    storage.upsert_daily(conn, _rows())
    cfg = FactorConfig(window=2, min_avg_value=0.0, min_traded_sessions=2, max_daily_move=0.5)
    items, rep = compute_factors(conn, as_of=D[3], cfg=cfg)
    return items, rep


def test_raw_factors_match_hand_calc(ranked):
    items, rep = ranked
    got = {it["symbol"]: it for it in items}
    assert rep["base_date"] == D[1]
    assert got["D"]["reason"] == "ngung_giao_dich" and not got["D"]["eligible"]
    assert got["A"]["momentum"] == pytest.approx(0.10)
    assert got["B"]["momentum"] == pytest.approx(-0.12)
    assert got["C"]["momentum"] == pytest.approx(0.05)
    assert [got[s]["avg_value"] for s in "ABC"] == pytest.approx([10, 20, 10])
    assert [got[s]["foreign_ratio"] for s in "ABC"] == pytest.approx([0.2, -0.5, 0.0])


def test_component_scores_match_hand_calc(ranked):
    comps = {c["symbol"]: c for c in component_scores(ranked[0])}
    assert [comps[s]["score_momentum"] for s in "ABC"] == pytest.approx([100, 0, 50])
    assert [comps[s]["score_liquidity"] for s in "ABC"] == pytest.approx([25, 100, 25])
    assert [comps[s]["score_foreign"] for s in "ABC"] == pytest.approx([100, 0, 50])


def test_equal_weight_ranking_matches_hand_calc(ranked):
    rows = rank_with_weights(component_scores(ranked[0]), EQUAL_WEIGHTS)
    assert [(r["symbol"], r["rank"]) for r in rows] == [("A", 1), ("C", 2), ("B", 3)]
    assert [r["score"] for r in rows] == pytest.approx([75, 125 / 3, 100 / 3])


def test_custom_weights_match_hand_calc(ranked):
    rows = rank_with_weights(component_scores(ranked[0]), weights_from_percent(50, 30, 20))
    assert {r["symbol"]: r["score"] for r in rows} == pytest.approx({"A": 77.5, "C": 42.5, "B": 30})


def test_price_jump_flag_with_default_band(tmp_path):
    conn = storage.connect(tmp_path / "j.db")
    storage.upsert_daily(conn, _rows())
    cfg = FactorConfig(window=2, min_avg_value=0.0, min_traded_sessions=2, max_daily_move=0.15)
    items, _ = compute_factors(conn, as_of=D[3], cfg=cfg)
    b = next(it for it in items if it["symbol"] == "B")      # 55 -> 44 = -20%
    assert b["reason"] == "gia_bat_thuong" and not b["eligible"]