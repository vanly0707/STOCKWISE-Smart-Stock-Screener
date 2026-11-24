"""In chi tiết cách tính điểm của MỘT mã để đối chiếu với bảng giá (SSI iBoard...).

Chạy:
    python -m src.finance.explain POW
    python -m src.finance.explain POW --as-of 2026-11-20 --out evidence/explain_POW.txt
"""
from __future__ import annotations

import argparse
import sys

from ..data import storage
from ..utils.output import redirect_stdout_to_file
from .factors import REASON_LABELS, compute_factors
from .run_ranking import _load_cfg
from .scoring import EQUAL_WEIGHTS, component_scores, rank_with_weights


def _num(v, nd=0) -> str:
    return "—" if v is None else f"{v:,.{nd}f}"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--config", default="config/settings.yaml")
    ap.add_argument("--as-of")
    ap.add_argument("--out", help="ghi kết quả ra file UTF-8")
    args = ap.parse_args(argv)
    if args.out:
        redirect_stdout_to_file(args.out)

    sym = args.symbol.strip().upper()
    cfg, fc = _load_cfg(args.config)
    conn = storage.connect(cfg["collect"]["db_path"])
    items, rep = compute_factors(conn, as_of=args.as_of, cfg=fc)
    item = next((it for it in items if it["symbol"] == sym), None)
    if item is None:
        print(f"Mã {sym} không có dữ liệu trong phạm vi {', '.join(rep['boards'])}.")
        conn.close()
        return 1

    dates = [rep["base_date"]] + rep["window_dates"]
    rows = {r["trading_date"]: r for r in conn.execute(
        """SELECT trading_date, close, total_match_value, foreign_buy_value, foreign_sell_value
           FROM daily_summary WHERE symbol = ? AND trading_date BETWEEN ? AND ?""",
        (sym, dates[0], dates[-1]))}
    conn.close()

    print(f"=== {sym} | ngày đánh giá {rep['as_of']} | cửa sổ {fc.window} phiên ===")
    print(f"{'Ngày':<12}{'Giá đóng cửa':>14}{'GT khớp (đồng)':>20}{'NN mua (đồng)':>18}{'NN bán (đồng)':>18}")
    for d in dates:
        r = rows.get(d)
        tag = "  <- ngày cơ sở" if d == rep["base_date"] else ""
        if r is None:
            print(f"{d:<12}{'(không giao dịch)':>14}{tag}")
        else:
            print(f"{d:<12}{_num(r['close']):>14}{_num(r['total_match_value']):>20}"
                  f"{_num(r['foreign_buy_value']):>18}{_num(r['foreign_sell_value']):>18}{tag}")

    win = [rows[d] for d in rep["window_dates"] if d in rows]
    value = sum(r["total_match_value"] or 0 for r in win)
    buy = sum(r["foreign_buy_value"] or 0 for r in win)
    sell = sum(r["foreign_sell_value"] or 0 for r in win)
    print("\n--- Cách tính ---")
    print(f"Động lượng   = giá {rep['as_of']} / giá gần nhất không muộn hơn {rep['base_date']} - 1"
          f" = {_num(item['momentum'] * 100 if item['momentum'] is not None else None, 2)}%")
    print(f"Thanh khoản  = tổng GT khớp {fc.window} phiên / {fc.window} = {_num(value)} / {fc.window}"
          f" = {_num(item['avg_value'] / 1e9 if item['avg_value'] is not None else None, 2)} tỷ đồng/phiên")
    print(f"Khối ngoại   = (mua - bán) / tổng GT khớp = ({_num(buy)} - {_num(sell)}) / {_num(value)}"
          f" = {_num(item['foreign_ratio'] * 100 if item['foreign_ratio'] is not None else None, 2)}%")
    print(f"Số phiên có giao dịch trong cửa sổ: {item['traded_sessions']}/{fc.window}")

    print("\n--- Kết quả ---")
    if not item["eligible"]:
        print(f"KHÔNG được xếp hạng: {REASON_LABELS.get(item['reason'], item['reason'])}")
        return 0
    ranked = rank_with_weights(component_scores(items), EQUAL_WEIGHTS)
    me = next(r for r in ranked if r["symbol"] == sym)
    print(f"Điểm thành phần (percentile 0-100 trong {len(ranked)} mã đủ điều kiện): "
          f"động lượng {me['score_momentum']:.1f} | thanh khoản {me['score_liquidity']:.1f} | "
          f"khối ngoại {me['score_foreign']:.1f}")
    print(f"Điểm tổng hợp (trọng số bằng nhau) = {me['score']:.1f} | hạng {me['rank']}/{len(ranked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())