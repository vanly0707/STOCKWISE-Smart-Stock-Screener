"""Tính ba yếu tố của STOCKWISE từ dữ liệu SQLite.

"5 phiên" luôn là 5 phiên của THỊ TRƯỜNG (lịch giao dịch lấy từ dữ liệu), không phải
5 dòng gần nhất của từng mã, vì SSI chỉ trả bản ghi cho phiên có khớp lệnh:
  - Thanh khoản: tổng giá trị khớp trong 5 phiên / 5 (phiên không giao dịch tính 0 đồng)
  - Động lượng: close(T) / close(T-5 phiên) - 1 (ngày cơ sở không giao dịch thì dùng giá gần nhất trước đó)
  - Dòng tiền ngoại: (mua - bán khối ngoại) / tổng giá trị khớp, cộng dồn trong cửa sổ
Phạm vi xếp hạng giới hạn theo `boards` (mặc định cấu hình: HOSE).
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class FactorConfig:
    window: int = 5
    min_avg_value: float = 500000000
    min_traded_sessions: int = 4
    max_daily_move: float = 0.075
    exclude_price_jumps: bool = True
    boards: tuple[str, ...] | None = None   # None = mọi sàn; ("HOSE",) = chỉ HOSE


REASON_LABELS = {
    "ok": "Đủ điều kiện",
    "ngung_giao_dich": "Không giao dịch trong cửa sổ",
    "thieu_gia_tri_khop": "Thiếu giá trị khớp",
    "thanh_khoan_thap": "Thanh khoản dưới ngưỡng",
    "it_phien": "Giao dịch quá ít phiên",
    "khong_du_lich_su": "Không đủ lịch sử để tính động lượng",
    "gia_bat_thuong": "Biến động giá bất thường (nghi điều chỉnh giá)",
}


def trading_calendar(conn: sqlite3.Connection) -> list[str]:
    """Các phiên giao dịch của thị trường (ISO), lấy từ dữ liệu đã thu thập."""
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT trading_date FROM daily_summary ORDER BY trading_date")]


def compute_factors(conn: sqlite3.Connection, as_of: str | None = None,
                    cfg: FactorConfig = FactorConfig()) -> tuple[list[dict], dict]:
    """Tính chỉ tiêu thô cho mọi mã thuộc phạm vi `cfg.boards` tại ngày `as_of` (mặc định: phiên mới nhất)."""
    cal = trading_calendar(conn)
    if not cal:
        raise ValueError("CSDL chưa có dữ liệu")
    as_of = as_of or cal[-1]
    if as_of not in cal:
        raise ValueError(f"Ngày {as_of} không phải phiên có dữ liệu")
    i = cal.index(as_of)
    w = cfg.window
    if i < w:
        raise ValueError(f"Cần ít nhất {w + 1} phiên dữ liệu, hiện có {i + 1}")

    pos = {d: k for k, d in enumerate(cal)}
    window_dates = cal[i - w + 1: i + 1]
    base_date = cal[i - w]
    lookback_start = cal[max(0, i - 2 * w)]
    win = set(window_dates)

    sql = """SELECT d.symbol, d.trading_date, d.close, d.total_match_value,
                    d.foreign_buy_value, d.foreign_sell_value, s.board
             FROM daily_summary d LEFT JOIN securities s ON s.symbol = d.symbol
             WHERE d.trading_date >= ? AND d.trading_date <= ?
             ORDER BY d.symbol, d.trading_date"""
    by_symbol: dict[str, list] = {}
    board_of: dict[str, str | None] = {}
    for r in conn.execute(sql, (lookback_start, as_of)):
        by_symbol.setdefault(r["symbol"], []).append(r)
        board_of[r["symbol"]] = r["board"]

    if cfg.boards:                           # giới hạn phạm vi theo sàn
        allowed = {b.upper() for b in cfg.boards}
        by_symbol = {sym: recs for sym, recs in by_symbol.items()
                     if str(board_of[sym] or "").upper() in allowed}

    items: list[dict] = []
    for sym, recs in by_symbol.items():
        in_win = [r for r in recs if r["trading_date"] in win]
        item = {"symbol": sym, "board": board_of[sym], "traded_sessions": len(in_win),
                "close": recs[-1]["close"], "momentum": None, "avg_value": None,
                "foreign_ratio": None, "eligible": False, "reason": ""}
        items.append(item)

        if not in_win:
            item["reason"] = "ngung_giao_dich"
            continue
        values = [r["total_match_value"] for r in in_win]
        if any(v is None for v in values):
            item["reason"] = "thieu_gia_tri_khop"
            continue

        total_value = float(sum(values))
        item["avg_value"] = total_value / w
        net_foreign = sum((r["foreign_buy_value"] or 0.0) - (r["foreign_sell_value"] or 0.0)
                          for r in in_win)
        item["foreign_ratio"] = net_foreign / total_value if total_value > 0 else None

        base_close = None
        for r in recs:                       # bản ghi cuối cùng không muộn hơn ngày cơ sở
            if r["trading_date"] <= base_date:
                base_close = r["close"]
        if base_close:
            item["momentum"] = recs[-1]["close"] / base_close - 1

        jump = False
        tail = [r for r in recs if r["trading_date"] >= base_date]
        for a, b in zip(tail, tail[1:]):
            if pos[b["trading_date"]] - pos[a["trading_date"]] == 1 and a["close"] > 0:
                if abs(b["close"] / a["close"] - 1) > cfg.max_daily_move:
                    jump = True
                    break

        if total_value <= 0 or item["avg_value"] < cfg.min_avg_value:
            item["reason"] = "thanh_khoan_thap"
        elif len(in_win) < cfg.min_traded_sessions:
            item["reason"] = "it_phien"
        elif item["momentum"] is None:
            item["reason"] = "khong_du_lich_su"
        elif jump and cfg.exclude_price_jumps:
            item["reason"] = "gia_bat_thuong"
        else:
            item["reason"] = "ok"
            item["eligible"] = True

    counts = Counter(it["reason"] for it in items)
    report = {"as_of": as_of, "base_date": base_date, "window_dates": window_dates,
              "boards": list(cfg.boards) if cfg.boards else ["HOSE", "HNX", "UPCOM"],
              "n_symbols": len(items), "n_eligible": counts.get("ok", 0),
              "by_reason": dict(counts)}
    return items, report