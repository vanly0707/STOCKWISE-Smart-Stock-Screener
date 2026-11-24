"""Kiểm tra độ nhạy của xếp hạng: trọng số, cửa sổ 5/10/20 phiên và ngưỡng thanh khoản.

Chạy: python -m src.finance.sensitivity
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import replace

from ..data import storage
from ..utils.output import redirect_stdout_to_file
from .factors import FactorConfig, compute_factors
from .run_ranking import _load_cfg
from .scoring import (EQUAL_WEIGHTS, compare_rankings, component_scores,
                      rank_with_weights, spearman, weights_from_percent)

# Ký hiệu: M = động lượng, L = thanh khoản, F = khối ngoại (số là % trọng số)
WEIGHT_SETS = {
    "Bằng nhau": EQUAL_WEIGHTS,
    "M50 L30 F20": weights_from_percent(50, 30, 20),
    "M20 L50 F30": weights_from_percent(20, 50, 30),
    "M20 L30 F50": weights_from_percent(20, 30, 50),
}


def rank_corr(rows_a: list[dict], rows_b: list[dict]) -> float:
    """Spearman trên tập mã chung của hai bảng xếp hạng."""
    sa = {r["symbol"]: r["score"] for r in rows_a}
    sb = {r["symbol"]: r["score"] for r in rows_b}
    common = sorted(set(sa) & set(sb))
    if len(common) < 3:
        return float("nan")
    rho = spearman([sa[s] for s in common], [sb[s] for s in common])
    return float("nan") if rho is None else rho


def _matrix(rankings: dict[str, list[dict]]) -> tuple[list[str], list[list[float]]]:
    names = list(rankings)
    return names, [[rank_corr(rankings[a], rankings[b]) for b in names] for a in names]


def _print_matrix(title: str, names: list[str], m: list[list[float]]) -> None:
    print(f"\n=== {title} ===")
    print(" " * 24 + " ".join(f"{n[:12]:>12}" for n in names))
    for name, row in zip(names, m):
        print(f"{name[:24]:<24}" + " ".join(f"{v:>12.3f}" for v in row))


def weight_sensitivity(items: list[dict]) -> tuple[list[str], list[list[float]]]:
    """Ma trận Spearman giữa điểm tổng hợp của các bộ trọng số."""
    comps = component_scores(items)
    return _matrix({name: rank_with_weights(comps, w) for name, w in WEIGHT_SETS.items()})


def window_sensitivity(conn, fc: FactorConfig, windows=(5, 10, 20)):
    """Ma trận Spearman giữa các cửa sổ; bỏ cửa sổ chưa đủ dữ liệu.

    Số phiên giao dịch tối thiểu co giãn theo cửa sổ (80%: 5->4, 10->8, 20->16).
    """
    rankings = {}
    for n in windows:
        cfg = replace(fc, window=n, min_traded_sessions=math.ceil(0.8 * n))
        try:
            items, _ = compute_factors(conn, cfg=cfg)
            rankings[f"{n} phiên"] = rank_with_weights(component_scores(items), EQUAL_WEIGHTS)
        except ValueError as exc:
            print(f"Bỏ cửa sổ {n} phiên: {exc}")
    return _matrix(rankings)


def threshold_sensitivity(conn, fc: FactorConfig, thresholds=(0.5e9, 1e9, 2e9), top_n=20):
    """So sánh các ngưỡng thanh khoản với ngưỡng cơ sở (giá trị đầu tiên trùng fc)."""
    out, base = [], None
    for thr in thresholds:
        items, rep = compute_factors(conn, cfg=replace(fc, min_avg_value=thr))
        try:
            rows = rank_with_weights(component_scores(items), EQUAL_WEIGHTS)
        except ValueError:          # ngưỡng quá cao: còn dưới 2 mã đủ điều kiện
            print(f"Bỏ ngưỡng {thr / 1e9:g} tỷ: còn {rep['n_eligible']} mã đủ điều kiện")
            continue
        if thr == fc.min_avg_value:
            base = rows
        out.append((thr, rep["n_eligible"], rows))
    if not out:
        return []
    base = base or out[0][2]
    return [(thr, n, compare_rankings(base, rows, top_n=top_n)) for thr, n, rows in out]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="ghi kết quả ra file UTF-8 (tránh lỗi font khi dùng > trong PowerShell)")
    args = ap.parse_args(argv)
    if args.out:
        redirect_stdout_to_file(args.out)

    cfg, fc = _load_cfg("config/settings.yaml")
    conn = storage.connect(cfg["collect"]["db_path"])

    items, rep = compute_factors(conn, cfg=fc)
    print(f"Phạm vi: {', '.join(rep['boards'])} | ngày đánh giá {rep['as_of']} | "
          f"{rep['n_eligible']}/{rep['n_symbols']} mã đủ điều kiện")

    print("Ký hiệu trọng số: M = động lượng, L = thanh khoản, F = khối ngoại (số là %)")
    _print_matrix("ĐỘ NHẠY THEO TRỌNG SỐ (Spearman)", *weight_sensitivity(items))
    _print_matrix("ĐỘ NHẠY THEO CỬA SỔ (Spearman, trọng số bằng nhau)",
                  *window_sensitivity(conn, fc))

    print(f"\n=== ĐỘ NHẠY THEO NGƯỠNG THANH KHOẢN (so với {fc.min_avg_value / 1e9:g} tỷ) ===")
    print("Ngưỡng (tỷ) | Số mã | Spearman | Trùng top 20")
    for thr, n, c in threshold_sensitivity(conn, fc):
        sp = "n/a" if c["spearman"] is None else f"{c['spearman']:.3f}"
        print(f"{thr / 1e9:>11g} | {n:>5} | {sp:>8} | {c['top_overlap']}/{c['top_n']}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())