"""Kiểm thử các hàm tính độ nhạy (không cần CSDL)."""
import math

import pytest

from src.data import storage
from src.finance.factors import FactorConfig
from src.finance.scoring import EQUAL_WEIGHTS, component_scores, rank_with_weights
from src.finance.sensitivity import (WEIGHT_SETS, rank_corr, threshold_sensitivity,
                                     weight_sensitivity)


def _rows(scores):
    return [{"symbol": s, "score": v} for s, v in scores.items()]


def test_rank_corr_identical_and_reversed():
    a = _rows({"A": 1, "B": 2, "C": 3, "D": 4})
    assert rank_corr(a, _rows({"A": 10, "B": 20, "C": 30, "D": 40})) == pytest.approx(1.0)
    assert rank_corr(a, _rows({"A": 4, "B": 3, "C": 2, "D": 1})) == pytest.approx(-1.0)


def test_rank_corr_uses_common_symbols_and_needs_three():
    a = _rows({"A": 1, "B": 2, "C": 3, "X": 9})
    b = _rows({"A": 1, "B": 2, "C": 3, "Y": 0})
    assert rank_corr(a, b) == pytest.approx(1.0)                 # chỉ so A, B, C
    assert math.isnan(rank_corr(_rows({"A": 1, "B": 2}), _rows({"A": 1, "B": 2})))


def test_weight_sensitivity_matrix_is_symmetric_with_unit_diagonal():
    items = [{"symbol": f"S{i}", "eligible": True, "momentum": (i % 7) / 10,
              "avg_value": 1e9 * (1 + (i * 3) % 11), "foreign_ratio": ((i * 5) % 9 - 4) / 100}
             for i in range(30)]
    names, m = weight_sensitivity(items)
    assert names == list(WEIGHT_SETS)
    for i in range(len(names)):
        assert m[i][i] == pytest.approx(1.0)
        for j in range(len(names)):
            assert m[i][j] == pytest.approx(m[j][i])
            assert -1.0 <= m[i][j] <= 1.0
    assert rank_with_weights(component_scores(items), EQUAL_WEIGHTS)[0]["rank"] == 1


def test_threshold_sensitivity_skips_thresholds_that_leave_too_few_stocks(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05",
            "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11"]
    storage.upsert_securities(conn, [{"symbol": s, "board": "HOSE", "icb_code": "1",
                                      "listed_share": 1.0} for s in ("AAA", "BBB", "CCC")])
    for k, sym in enumerate(("AAA", "BBB", "CCC")):
        for i, d in enumerate(days):
            storage.upsert_daily(conn, [{
                "symbol": sym, "trading_date": d, "close": 10000.0 + 100 * i * (k + 1),
                "total_match": 1000.0, "total_match_value": 2e9 * (k + 1),
                "foreign_buy_value": 1e8 * k, "foreign_sell_value": 0.0}])
    fc = FactorConfig(boards=("HOSE",))
    result = threshold_sensitivity(conn, fc, thresholds=(1e9, 1e15))
    assert [thr for thr, _, _ in result] == [1e9]                  # ngưỡng 1e15 bị bỏ qua, không sập
    assert result[0][1] == 3
    assert result[0][2]["spearman"] == pytest.approx(1.0)
    assert threshold_sensitivity(conn, fc, thresholds=(1e15,)) == []
    conn.close()