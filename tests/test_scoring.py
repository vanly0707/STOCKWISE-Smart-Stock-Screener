"""Kiểm thử percentile rank, trọng số, xếp hạng và so sánh độ nhạy."""
import pytest

from src.finance.scoring import (EQUAL_WEIGHTS, average_ranks, compare_rankings,
                                 component_scores, percentile_ranks, rank_with_weights,
                                 score_universe, spearman, validate_weights, weighted_score,
                                 weights_from_percent)


def _item(sym, m, v, f, eligible=True):
    return {"symbol": sym, "eligible": eligible, "momentum": m, "avg_value": v,
            "foreign_ratio": f}


UNIVERSE = [
    _item("A", 0.10, 1e9, -0.10),
    _item("B", 0.00, 5e9, 0.00),
    _item("C", -0.10, 9e9, 0.10),
    _item("Z", 0.50, 9e12, 0.9, eligible=False),    # không đủ điều kiện: không được tính
]


def test_percentile_ranks_basic_and_ties():
    assert percentile_ranks([10, 20, 30]) == [0.0, 50.0, 100.0]
    assert percentile_ranks([5]) == [50.0]
    assert percentile_ranks([]) == []
    assert percentile_ranks([1, 1, 2]) == [25.0, 25.0, 100.0]       # đồng hạng: phân vị trung bình
    assert average_ranks([3, 1, 2]) == [3.0, 1.0, 2.0]


def test_equal_weight_example_from_proposal():
    # Ví dụ trong đề xuất: (85 + 70 + 55) / 3 = 70
    assert weighted_score((85, 70, 55), EQUAL_WEIGHTS) == pytest.approx(70.0)


def test_weights_validation():
    validate_weights(EQUAL_WEIGHTS)
    assert weights_from_percent(50, 30, 20) == pytest.approx((0.5, 0.3, 0.2))
    for bad in [(60, 30, 20), (-10, 60, 50), (50, 30, 10)]:
        with pytest.raises(ValueError):
            weights_from_percent(*bad)
    with pytest.raises(ValueError):
        validate_weights((0.5, 0.5, 0.5))
    with pytest.raises(ValueError):
        validate_weights((1.5, -0.5, 0.0))


def test_equal_weight_ranking_excludes_ineligible():
    rows = score_universe(UNIVERSE)
    assert [r["symbol"] for r in rows] == ["C", "B", "A"]
    assert [r["rank"] for r in rows] == [1, 2, 3]
    assert rows[0]["score"] == pytest.approx((0 + 100 + 100) / 3)
    assert rows[2]["score"] == pytest.approx((100 + 0 + 0) / 3)
    assert all(r["symbol"] != "Z" for r in rows)


def test_custom_weights_change_ranking_and_recompute_fast():
    comps = component_scores(UNIVERSE)                      # tính một lần
    equal = rank_with_weights(comps)
    momentum_first = rank_with_weights(comps, weights_from_percent(80, 10, 10))
    assert [r["symbol"] for r in momentum_first] == ["A", "B", "C"]
    assert momentum_first[0]["score"] == pytest.approx(80.0)
    # Hai chiến lược cho hai danh sách ngược nhau
    cmp = compare_rankings(equal, momentum_first, top_n=1)
    assert cmp["spearman"] == pytest.approx(-1.0)
    assert cmp["top_overlap"] == 0


def test_tied_scores_share_rank():
    rows = score_universe([_item("A", 0.1, 5e9, 0.0), _item("B", 0.1, 5e9, 0.0),
                           _item("C", -0.1, 1e9, -0.1)])
    assert [(r["symbol"], r["rank"]) for r in rows] == [("A", 1), ("B", 1), ("C", 3)]


def test_needs_at_least_two_eligible():
    with pytest.raises(ValueError):
        score_universe([_item("A", 0.1, 1e9, 0.0), _item("B", 0.2, 1e9, 0.0, eligible=False)])


def test_spearman():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 1, 1], [1, 2, 3]) is None                    # dãy không đổi
    with pytest.raises(ValueError):
        spearman([1], [1])