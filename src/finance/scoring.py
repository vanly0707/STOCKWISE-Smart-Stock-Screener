"""Chấm điểm và xếp hạng cổ phiếu: percentile rank 0-100, trọng số bằng nhau hoặc tùy chỉnh.

Cả ba yếu tố đều theo chiều "cao hơn thì tốt hơn":
  - Động lượng: tỷ suất sinh lời cao hơn
  - Thanh khoản: giá trị khớp bình quân cao hơn
  - Dòng tiền ngoại: tỷ lệ mua ròng cao hơn
Các mã đồng hạng (ví dụ nhiều mã cùng tỷ lệ khối ngoại = 0) nhận phân vị trung bình.
"""
from __future__ import annotations

import math

EQUAL_WEIGHTS = (1 / 3, 1 / 3, 1 / 3)   # mô hình cơ sở (Baseline)
FACTOR_KEYS = ("momentum", "avg_value", "foreign_ratio")
SCORE_KEYS = ("score_momentum", "score_liquidity", "score_foreign")


def average_ranks(values: list[float]) -> list[float]:
    """Hạng 1..n (tăng dần); đồng hạng nhận hạng trung bình."""
    n = len(values)
    order = sorted(range(n), key=lambda k: values[k])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def percentile_ranks(values: list[float]) -> list[float]:
    """Chuẩn hóa về thang 0-100: thấp nhất = 0, cao nhất = 100."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [50.0]
    return [(r - 1) / (n - 1) * 100 for r in average_ranks(values)]


def validate_weights(weights: tuple[float, float, float]) -> None:
    if len(weights) != 3 or any(w < 0 for w in weights):
        raise ValueError("Cần đúng 3 trọng số không âm")
    if abs(sum(weights) - 1.0) > 1e-6:
        raise ValueError("Tổng trọng số phải bằng 100%")


def weights_from_percent(momentum: float, liquidity: float, foreign: float
                         ) -> tuple[float, float, float]:
    """Đổi trọng số nhập theo % (tổng 100) sang dạng tỷ lệ."""
    if min(momentum, liquidity, foreign) < 0:
        raise ValueError("Trọng số không được âm")
    if abs(momentum + liquidity + foreign - 100.0) > 0.01:
        raise ValueError("Tổng trọng số phải bằng 100%")
    total = momentum + liquidity + foreign
    return (momentum / total, liquidity / total, foreign / total)


def weighted_score(components: tuple[float, float, float],
                   weights: tuple[float, float, float] = EQUAL_WEIGHTS) -> float:
    return sum(c * w for c, w in zip(components, weights))


def component_scores(items: list[dict]) -> list[dict]:
    """Điểm thành phần (0-100) cho các mã đủ điều kiện. Tính một lần, đổi trọng số tính lại rất nhanh."""
    pool = [it for it in items if it.get("eligible")]
    if len(pool) < 2:
        raise ValueError("Cần ít nhất 2 cổ phiếu đủ điều kiện để xếp hạng")
    cols = [percentile_ranks([it[k] for it in pool]) for k in FACTOR_KEYS]
    return [{**it, **dict(zip(SCORE_KEYS, scores))}
            for it, *scores in zip(pool, *cols)]


def rank_with_weights(components: list[dict],
                      weights: tuple[float, float, float] = EQUAL_WEIGHTS) -> list[dict]:
    """Tính điểm tổng hợp và thứ hạng (đồng điểm cùng hạng, hạng kiểu 1-2-2-4)."""
    validate_weights(weights)
    rows = []
    for c in components:
        score = weighted_score(tuple(c[k] for k in SCORE_KEYS), weights)
        rows.append({**c, "score": score})
    rows.sort(key=lambda r: (-round(r["score"], 9), r["symbol"]))
    prev_score, prev_rank = None, 0
    for pos, r in enumerate(rows, 1):
        key = round(r["score"], 9)
        r["rank"] = prev_rank if key == prev_score else pos
        prev_score, prev_rank = key, r["rank"]
    return rows


def score_universe(items: list[dict],
                   weights: tuple[float, float, float] = EQUAL_WEIGHTS) -> list[dict]:
    return rank_with_weights(component_scores(items), weights)


def spearman(a: list[float], b: list[float]) -> float | None:
    """Hệ số tương quan hạng Spearman; None nếu một dãy không đổi."""
    if len(a) != len(b) or len(a) < 2:
        raise ValueError("Hai dãy phải cùng độ dài và có ít nhất 2 phần tử")
    ra, rb = average_ranks(a), average_ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        return None
    return cov / math.sqrt(va * vb)


def compare_rankings(rows_a: list[dict], rows_b: list[dict], top_n: int = 20) -> dict:
    """So sánh hai bảng xếp hạng (ví dụ trọng số bằng nhau vs ưu tiên động lượng)."""
    score_b = {r["symbol"]: r["score"] for r in rows_b}
    common = [r["symbol"] for r in rows_a if r["symbol"] in score_b]
    score_a = {r["symbol"]: r["score"] for r in rows_a}
    top_a = {r["symbol"] for r in rows_a[:top_n]}
    top_b = {r["symbol"] for r in rows_b[:top_n]}
    return {
        "spearman": spearman([score_a[s] for s in common], [score_b[s] for s in common])
        if len(common) >= 2 else None,
        "top_n": top_n,
        "top_overlap": len(top_a & top_b),
    }