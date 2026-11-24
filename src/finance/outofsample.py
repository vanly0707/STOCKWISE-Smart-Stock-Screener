"""Kiểm tra ngoài mẫu (walk-forward): điểm STOCKWISE tại ngày t có tương quan với lợi suất SAU t không?

Chống nhìn trước (look-ahead): điểm tại t chỉ dùng dữ liệu <= t (compute_factors cắt ở as_of);
lợi suất tương lai tính từ close(t) đến close(t + h phiên). Không tối ưu trọng số hay ngưỡng
trên chính kết quả này.

Chỉ số mỗi ngày t:
  - IC: hệ số Spearman giữa điểm (và từng điểm thành phần) với lợi suất tương lai
  - spread: lợi suất TB của nhóm điểm cao nhất (top 20%) trừ nhóm thấp nhất (20% cuối)
Tổng hợp: IC trung bình, độ lệch chuẩn, t-stat, tỷ lệ ngày IC > 0.
Mặc định lấy mỗi h phiên một lần (step = h) để các cửa sổ lợi suất không chồng lấn.

Đây là phép kiểm tra thống kê trên mẫu ngắn, không phải bằng chứng mô hình dự báo được.

Chạy:
    python -m src.finance.outofsample --horizon 5
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import statistics
import sys
from bisect import bisect_right

from .factors import FactorConfig, compute_factors, trading_calendar
from .scoring import EQUAL_WEIGHTS, SCORE_KEYS, component_scores, rank_with_weights, spearman

MIN_NAMES = 30   # cần tối thiểu ngần ấy mã có lợi suất tương lai để tính IC của một ngày


def load_closes(conn: sqlite3.Connection) -> dict[str, tuple[list[str], list[float]]]:
    """{mã: (các ngày tăng dần, giá đóng cửa)}"""
    out: dict[str, tuple[list[str], list[float]]] = {}
    for r in conn.execute("SELECT symbol, trading_date, close FROM daily_summary "
                          "WHERE close IS NOT NULL ORDER BY symbol, trading_date"):
        d, c = out.setdefault(r["symbol"], ([], []))
        d.append(r["trading_date"])
        c.append(r["close"])
    return out


def forward_return(series: tuple[list[str], list[float]], t: str, t_end: str,
                   calendar_pos: dict[str, int], max_move: float | None) -> float | None:
    """close(t_end) / close(t) - 1; ngày không giao dịch dùng giá gần nhất không muộn hơn.

    Trả None nếu không có giá tại t, không có giá mới hơn t, hoặc (khi max_move đặt) có biến
    động giá 1 phiên vượt ngưỡng trong (t, t_end] - nghi giá chưa điều chỉnh.
    """
    dates, closes = series
    i0 = bisect_right(dates, t) - 1
    i1 = bisect_right(dates, t_end) - 1
    if i0 < 0 or dates[i0] != t or i1 <= i0 or closes[i0] <= 0:
        return None
    if max_move is not None:
        for k in range(i0 + 1, i1 + 1):
            if calendar_pos[dates[k]] - calendar_pos[dates[k - 1]] == 1 and closes[k - 1] > 0:
                if abs(closes[k] / closes[k - 1] - 1) > max_move:
                    return None
    return closes[i1] / closes[i0] - 1


def _spread(rows: list[dict], fwd: dict[str, float], frac: float = 0.2) -> float | None:
    sel = [r for r in rows if r["symbol"] in fwd]
    k = int(len(sel) * frac)
    if k < 1:
        return None
    ordered = sorted(sel, key=lambda r: -r["score"])
    top = statistics.fmean(fwd[r["symbol"]] for r in ordered[:k])
    bot = statistics.fmean(fwd[r["symbol"]] for r in ordered[-k:])
    return top - bot


def evaluate_date(conn, closes, cal, t: str, h: int, cfg: FactorConfig,
                  weights=EQUAL_WEIGHTS, drop_jumps: bool = True) -> dict | None:
    i = cal.index(t)
    if i + h >= len(cal) or i < cfg.window:
        return None
    t_end = cal[i + h]
    pos = {d: k for k, d in enumerate(cal)}
    items, _ = compute_factors(conn, as_of=t, cfg=cfg)
    rows = rank_with_weights(component_scores(items), weights)
    fwd: dict[str, float] = {}
    n_dropped = 0
    for r in rows:
        s = closes.get(r["symbol"])
        v = forward_return(s, t, t_end, pos, cfg.max_daily_move if drop_jumps else None) if s else None
        if v is None:
            n_dropped += 1
        else:
            fwd[r["symbol"]] = v
    kept = [r for r in rows if r["symbol"] in fwd]
    if len(kept) < MIN_NAMES:
        return None
    y = [fwd[r["symbol"]] for r in kept]
    res = {"date": t, "end": t_end, "n": len(kept), "n_dropped": n_dropped,
           "ic": spearman([r["score"] for r in kept], y),
           "spread": _spread(kept, fwd), "mean_fwd": statistics.fmean(y)}
    for key in SCORE_KEYS:
        res["ic_" + key] = spearman([r[key] for r in kept], y)
    return res


def summarize(values: list[float | None]) -> dict:
    v = [x for x in values if x is not None]
    n = len(v)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "t": None, "hit": None}
    mean = statistics.fmean(v)
    std = statistics.stdev(v) if n > 1 else None
    t = mean / (std / math.sqrt(n)) if std else None
    return {"n": n, "mean": mean, "std": std, "t": t, "hit": sum(x > 0 for x in v) / n}


def run_oos(conn: sqlite3.Connection, h: int = 5, cfg: FactorConfig = FactorConfig(),
            weights=EQUAL_WEIGHTS, step: int | None = None, drop_jumps: bool = True) -> dict:
    cal = trading_calendar(conn)
    closes = load_closes(conn)
    step = step or h
    first = cfg.window
    days = []
    for idx in range(first, len(cal) - h, step):
        try:
            r = evaluate_date(conn, closes, cal, cal[idx], h, cfg, weights, drop_jumps)
        except ValueError:      # ngày đó không đủ mã đủ điều kiện để xếp hạng: bỏ qua
            continue
        if r:
            days.append(r)
    summary = {"ic": summarize([d["ic"] for d in days]),
               "spread": summarize([d["spread"] for d in days])}
    for key in SCORE_KEYS:
        summary["ic_" + key] = summarize([d["ic_" + key] for d in days])
    return {"horizon": h, "step": step, "n_dates": len(days), "days": days, "summary": summary,
            "note": ("Mẫu ngắn, ít quan sát: t-stat chỉ mang tính tham khảo."
                     if len(days) < 30 else "")}


def _fmt(x, pct=False, nd=3):
    return "n/a" if x is None else (f"{x * 100:.2f}%" if pct else f"{x:.{nd}f}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    import yaml
    from ..data import storage
    from .run_ranking import _load_cfg
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/settings.yaml")
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--step", type=int)
    ap.add_argument("--no-jump-filter", action="store_true")
    args = ap.parse_args(argv)
    cfg, fc = _load_cfg(args.config)
    conn = storage.connect(cfg["collect"]["db_path"])
    res = run_oos(conn, args.horizon, fc, step=args.step, drop_jumps=not args.no_jump_filter)
    print(f"Kiểm tra ngoài mẫu: lợi suất {res['horizon']} phiên sau, "
          f"{res['n_dates']} ngày đánh giá (bước {res['step']} phiên)")
    print(f"{'Ngày':<12}{'Số mã':>6}{'Loại':>6}{'IC':>8}{'Spread':>9}")
    for d in res["days"]:
        print(f"{d['date']:<12}{d['n']:>6}{d['n_dropped']:>6}{_fmt(d['ic']):>8}"
              f"{_fmt(d['spread'], pct=True):>9}")
    print()
    for k, s in res["summary"].items():
        pct = k == "spread"
        print(f"{k:<20} n={s['n']:<3} TB={_fmt(s['mean'], pct)} lệch chuẩn={_fmt(s['std'], pct)} "
              f"t={_fmt(s['t'], nd=2)} tỷ lệ>0={_fmt(s['hit'], nd=2)}")
    if res["note"]:
        print("\nLưu ý:", res["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())