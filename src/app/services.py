"""Lớp dịch vụ cho giao diện STOCKWISE: không phụ thuộc Streamlit/Plotly nên kiểm thử được.

Giao diện (main.py) chỉ gọi các hàm ở đây rồi vẽ; mọi quyết định về dữ liệu, trạng thái và
cách diễn giải nằm trong file này.
"""
from __future__ import annotations

import math
import sqlite3
import statistics
from dataclasses import dataclass, replace
from datetime import date

from ..data import storage
from ..finance.factors import REASON_LABELS, FactorConfig, compute_factors, trading_calendar
from ..finance.scoring import (EQUAL_WEIGHTS, SCORE_KEYS, component_scores, rank_with_weights,
                               weights_from_percent)

FACTOR_LABELS = {"score_momentum": "Động lượng", "score_liquidity": "Thanh khoản",
                 "score_foreign": "Khối ngoại"}
TY = 1e9
STALE_DAYS = 4   # quá 4 ngày lịch kể từ phiên cuối là "cũ" (dư cho cuối tuần, lễ ngắn)


# ---------------------------------------------------------------- cấu hình / trạng thái
def make_factor_config(base: FactorConfig, window: int, min_avg_value: float) -> FactorConfig:
    """Cửa sổ khác nhau thì số phiên giao dịch tối thiểu co giãn theo (80%: 5->4, 10->8, 20->16)."""
    return replace(base, window=window, min_avg_value=min_avg_value,
                   min_traded_sessions=math.ceil(0.8 * window))


@dataclass
class DataStatus:
    level: str                       # ok | warn | error
    message: str
    last_date: str | None = None
    n_sessions: int = 0
    n_symbols: int = 0
    last_run_at: str | None = None
    last_run_note: str | None = None


def get_status(conn: sqlite3.Connection, today: date | None = None,
               stale_days: int = STALE_DAYS) -> DataStatus:
    """Trạng thái dữ liệu để hiển thị ở đầu trang; không bao giờ ném lỗi ra giao diện."""
    try:
        st = storage.stats(conn)
        run = conn.execute(
            "SELECT started_at, finished_at, note FROM collect_runs ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error as exc:
        return DataStatus("error", f"Không đọc được cơ sở dữ liệu: {exc}")

    if not st["n_rows"]:
        return DataStatus("error", "Cơ sở dữ liệu chưa có dữ liệu giá. "
                                   "Hãy chạy: python -m src.data.collector")
    today = today or storage.now_vn().date()
    last = date.fromisoformat(st["max_date"])
    age = (today - last).days
    run_at = run["finished_at"] or run["started_at"] if run else None
    run_note = run["note"] if run else None
    base = dict(last_date=st["max_date"], n_sessions=st["n_dates"], n_symbols=st["n_symbols"],
                last_run_at=run_at, last_run_note=run_note)
    if run_note and run_note != "hoàn tất":
        return DataStatus("warn", f"Lượt thu thập gần nhất chưa hoàn tất: {run_note}", **base)
    if age > stale_days:
        return DataStatus("warn", f"Dữ liệu đã cũ: phiên cuối là {st['max_date']} "
                                  f"({age} ngày trước). Hãy chạy lại bộ thu thập.", **base)
    return DataStatus("ok", f"Dữ liệu cập nhật đến phiên {st['max_date']}.", **base)


def available_dates(conn: sqlite3.Connection) -> list[str]:
    """Các ngày đánh giá có thể chọn (mới nhất trước)."""
    return list(reversed(trading_calendar(conn)))


def max_window(conn: sqlite3.Connection, as_of: str) -> int:
    """Cửa sổ lớn nhất tính được tại ngày đánh giá (cần w + 1 phiên)."""
    cal = trading_calendar(conn)
    return cal.index(as_of) if as_of in cal else 0


# ---------------------------------------------------------------- xếp hạng
def parse_weights(mode: str, m: float = 50, l: float = 30, f: float = 20
                  ) -> tuple[tuple[float, float, float] | None, str | None]:
    """Trả về (trọng số, thông báo lỗi). mode: 'equal' hoặc 'custom' (m, l, f theo %)."""
    if mode == "equal":
        return EQUAL_WEIGHTS, None
    try:
        return weights_from_percent(m, l, f), None
    except ValueError:
        return None, f"Tổng trọng số hiện là {m + l + f:g}%, cần đúng 100%."


def build_ranking(conn: sqlite3.Connection, fc: FactorConfig, weights, as_of: str | None = None):
    """Trả về (tất cả mã kèm lý do, báo cáo, bảng xếp hạng). Có thể ném ValueError (chưa đủ dữ liệu)."""
    items, rep = compute_factors(conn, as_of=as_of, cfg=fc)
    rows = rank_with_weights(component_scores(items), weights)
    return items, rep, rows


def summary_metrics(items: list[dict], rows: list[dict]) -> dict:
    """Các chỉ số tổng hợp cho đầu trang xếp hạng."""
    n_all = len(items)
    n_ok = len(rows)
    median = statistics.median(r["score"] for r in rows) if rows else float("nan")
    return {
        "n_total": n_all,
        "n_eligible": n_ok,
        "pct_eligible": 100 * n_ok / n_all if n_all else 0.0,
        "pct_positive_momentum": 100 * sum(r["momentum"] > 0 for r in rows) / n_ok if n_ok else 0.0,
        "avg_value_total_bn": sum(r["avg_value"] for r in rows) / TY,
        "net_foreign_bn": sum(r["foreign_ratio"] * r["avg_value"] for r in rows) / TY,  # tỷ/phiên
        "median_score": median,
    }


def rows_to_table(rows: list[dict], query: str = "", top: int | None = None) -> list[dict]:
    """Bảng hiển thị: lọc theo mã (chứa chuỗi, không phân biệt hoa thường), cắt top N."""
    q = query.strip().upper()
    sel = [r for r in rows if q in r["symbol"]] if q else list(rows)
    if top:
        sel = sel[:top]
    return [{
        "Hạng": r["rank"], "Mã": r["symbol"], "Điểm": round(r["score"], 1),
        "Động lượng": round(r["score_momentum"], 1), "Thanh khoản": round(r["score_liquidity"], 1),
        "Khối ngoại": round(r["score_foreign"], 1),
        "Sinh lời (%)": round(r["momentum"] * 100, 2),
        "GT khớp TB (tỷ/phiên)": round(r["avg_value"] / TY, 2),
        "Mua ròng NN (%GT)": round(r["foreign_ratio"] * 100, 2),
    } for r in sel]


def contributions(rows: list[dict], weights, top: int = 15) -> list[dict]:
    """Đóng góp có trọng số của từng yếu tố vào điểm tổng, cho biểu đồ cột chồng."""
    out = []
    for r in rows[:top]:
        out.append({"Mã": r["symbol"], **{FACTOR_LABELS[k]: r[k] * w
                                           for k, w in zip(SCORE_KEYS, weights)}})
    return out


def excluded_table(items: list[dict]) -> list[dict]:
    return [{"Mã": it["symbol"], "Lý do": REASON_LABELS.get(it["reason"], it["reason"])}
            for it in items if not it["eligible"]]


def reason_counts(items: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        label = REASON_LABELS.get(it["reason"], it["reason"])
        out[label] = out.get(label, 0) + 1
    return out


# ---------------------------------------------------------------- chi tiết một mã
def price_history(conn: sqlite3.Connection, symbol: str, limit: int = 60) -> list[dict]:
    """Giá đóng cửa, giá trị khớp và mua ròng khối ngoại theo ngày (tăng dần)."""
    rows = conn.execute(
        """SELECT trading_date, close, total_match_value, foreign_buy_value, foreign_sell_value
           FROM daily_summary WHERE symbol = ? ORDER BY trading_date DESC LIMIT ?""",
        (symbol, int(limit))).fetchall()
    return [{"date": r["trading_date"], "close": r["close"],
             "value_bn": (r["total_match_value"] or 0.0) / TY,
             "foreign_net_bn": ((r["foreign_buy_value"] or 0.0) - (r["foreign_sell_value"] or 0.0)) / TY}
            for r in reversed(rows)]


def _band(score: float) -> str:
    if score >= 80:
        return "thuộc nhóm cao nhất (top 20%)"
    if score >= 60:
        return "trên mức trung bình"
    if score >= 40:
        return "ở mức trung bình"
    if score >= 20:
        return "dưới mức trung bình"
    return "thuộc nhóm thấp nhất (20% cuối)"


def explain(row: dict, n_ranked: int) -> str:
    """Diễn giải thứ hạng bằng quy tắc cố định (không dùng mô hình ngôn ngữ), dựa trên số liệu thật."""
    parts = []
    for key, label in FACTOR_LABELS.items():
        parts.append((label, row[key]))
    best = max(parts, key=lambda p: p[1])
    worst = min(parts, key=lambda p: p[1])
    return (
        f"{row['symbol']} xếp hạng {row['rank']}/{n_ranked} với điểm {row['score']:.1f}. "
        f"Động lượng {row['momentum'] * 100:+.2f}% ({_band(row['score_momentum'])}); "
        f"giá trị khớp bình quân {row['avg_value'] / TY:,.2f} tỷ đồng/phiên "
        f"({_band(row['score_liquidity'])}); "
        f"khối ngoại mua ròng {row['foreign_ratio'] * 100:+.2f}% giá trị khớp "
        f"({_band(row['score_foreign'])}). "
        f"Yếu tố mạnh nhất là {best[0].lower()} ({best[1]:.0f}/100), "
        f"yếu nhất là {worst[0].lower()} ({worst[1]:.0f}/100). "
        "Điểm là thứ hạng tương đối trong rổ cổ phiếu đủ điều kiện tại ngày đánh giá, "
        "không phải dự báo lợi nhuận."
    )
