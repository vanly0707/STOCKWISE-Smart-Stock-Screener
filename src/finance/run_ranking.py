"""Xem nhanh kết quả xếp hạng trên dữ liệu thật (phạm vi theo settings.yaml, mặc định HOSE).

Chạy:
    python -m src.finance.run_ranking
    python -m src.finance.run_ranking --weights 50 30 20
    python -m src.finance.run_ranking --as-of 2026-11-13 --top 30
"""
from __future__ import annotations

import argparse
import sys

import yaml

from ..data import storage
from ..utils.output import redirect_stdout_to_file
from .factors import REASON_LABELS, FactorConfig, compute_factors
from .scoring import (EQUAL_WEIGHTS, component_scores, compare_rankings, rank_with_weights,
                      weights_from_percent)


def _load_cfg(path: str) -> tuple[dict, FactorConfig]:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    s = cfg.get("scoring", {})
    fc = FactorConfig(window=s.get("window", 5), min_avg_value=s.get("min_avg_value",500000000),
                      min_traded_sessions=s.get("min_traded_sessions", 4),
                      max_daily_move=s.get("max_daily_move", 0.075),
                      exclude_price_jumps=s.get("exclude_price_jumps", True),
                      boards=tuple(s["boards"]) if s.get("boards") else None)
    return cfg, fc


def _print_table(rows: list[dict], top: int) -> None:
    print(f"{'Hạng':>4} {'Mã':<5} {'Sàn':<6} {'Điểm':>6} {'Đ.lượng':>8} {'T.khoản':>8} "
          f"{'K.ngoại':>8} | {'Sinh lời':>9} {'GT khớp(tỷ)':>12} {'Mua ròng NN':>11}")
    for r in rows[:top]:
        print(f"{r['rank']:>4} {r['symbol']:<5} {str(r['board']):<6} {r['score']:>6.1f} "
              f"{r['score_momentum']:>8.1f} {r['score_liquidity']:>8.1f} {r['score_foreign']:>8.1f} | "
              f"{r['momentum'] * 100:>8.2f}% {r['avg_value'] / 1e9:>12.2f} "
              f"{r['foreign_ratio'] * 100:>10.2f}%")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/settings.yaml")
    ap.add_argument("--as-of")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--weights", type=float, nargs=3, metavar=("M", "L", "F"),
                    help="trọng số %% cho động lượng, thanh khoản, khối ngoại (tổng 100)")
    ap.add_argument("--out", help="ghi kết quả ra file UTF-8 (tránh lỗi font khi dùng > trong PowerShell)")
    args = ap.parse_args(argv)
    if args.out:
        redirect_stdout_to_file(args.out)

    cfg, fc = _load_cfg(args.config)
    conn = storage.connect(cfg["collect"]["db_path"])
    items, rep = compute_factors(conn, as_of=args.as_of, cfg=fc)
    conn.close()

    print(f"Phạm vi: {', '.join(rep['boards'])}")
    print(f"Ngày đánh giá: {rep['as_of']} | cửa sổ {fc.window} phiên: "
          f"{rep['window_dates'][0]} -> {rep['window_dates'][-1]} | ngày cơ sở: {rep['base_date']}")
    print(f"Đủ điều kiện xếp hạng: {rep['n_eligible']}/{rep['n_symbols']} mã")
    for reason, n in sorted(rep["by_reason"].items(), key=lambda kv: -kv[1]):
        print(f"   {REASON_LABELS.get(reason, reason):<55} {n:>5}")

    comps = component_scores(items)
    base = rank_with_weights(comps, EQUAL_WEIGHTS)
    print(f"\n=== TRỌNG SỐ BẰNG NHAU (33,33% x 3), top {args.top} ===")
    _print_table(base, args.top)

    custom_w = weights_from_percent(*(args.weights or (50, 30, 20)))
    custom = rank_with_weights(comps, custom_w)
    label = "/".join(f"{w * 100:g}%" for w in custom_w)
    print(f"\n=== TRỌNG SỐ TÙY CHỈNH ({label}), top {args.top} ===")
    _print_table(custom, args.top)

    cmp = compare_rankings(base, custom, top_n=min(args.top, len(base)))
    sp = "n/a" if cmp["spearman"] is None else f"{cmp['spearman']:.3f}"
    print(f"\nĐộ nhạy: Spearman = {sp} | trùng {cmp['top_overlap']}/{cmp['top_n']} mã trong top {cmp['top_n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())