"""Làm sạch dữ liệu securitiesSummary của SSI trước khi lưu.

Quy ước đơn vị (đã đối chiếu với dữ liệu thật):
- close: đồng/cổ phiếu (53600 = 53.600 đ)
- totalMatchValue, totalForeignBuyValue, totalForeignSellValue: đồng
- totalMatch, totalForeignBuy, totalForeignSell: cổ phiếu
- tradingDate: chuỗi 'YYYY/MM/DD'
"""
from __future__ import annotations

import math
from datetime import date, datetime

DATE_FORMATS = ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y")

# tên trường SSI -> tên cột trong DB
NUMERIC_FIELDS = {
    "close": "close",
    "totalMatch": "total_match",
    "totalMatchValue": "total_match_value",
    "totalForeignBuy": "foreign_buy_vol",
    "totalForeignBuyValue": "foreign_buy_value",
    "totalForeignSell": "foreign_sell_vol",
    "totalForeignSellValue": "foreign_sell_value",
    "remainForeignRoom": "remain_foreign_room",
    "totalForeignRoom": "total_foreign_room",
}


def to_float(value) -> float | None:
    """Ép về số thực; trả None nếu thiếu hoặc không hợp lệ."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        out = float(value)
    else:
        text = str(value).strip().replace(",", "")
        if text in ("", "-", "--", "null", "None", "NaN"):
            return None
        try:
            out = float(text)
        except ValueError:
            return None
    return out if math.isfinite(out) else None


def parse_date(value) -> date | None:
    """Đọc ngày giao dịch; thử nhiều định dạng, trả None nếu không đọc được."""
    if value is None:
        return None
    text = str(value).strip()[:10]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def clean_summary_rows(rows: list[dict], symbol: str | None = None) -> tuple[list[dict], dict]:
    """Làm sạch danh sách bản ghi của một mã.

    Trả về (danh sách bản ghi sạch sắp xếp theo ngày tăng dần, báo cáo chất lượng).
    - bỏ bản ghi thiếu mã, sai ngày, hoặc giá đóng cửa không dương
    - gộp bản ghi trùng (mã, ngày), giữ bản ghi xuất hiện sau cùng
    - giá trị âm ở các trường số được đặt thành None (không bịa số liệu)
    """
    report = {"rows_in": len(rows), "rows_out": 0, "missing_symbol": 0,
              "bad_date": 0, "bad_close": 0, "duplicates": 0, "negative_values": 0}
    seen: dict[tuple[str, str], dict] = {}

    for row in rows:
        sym = str(row.get("symbol") or symbol or "").strip().upper()
        if not sym:
            report["missing_symbol"] += 1
            continue
        d = parse_date(row.get("tradingDate"))
        if d is None:
            report["bad_date"] += 1
            continue

        rec: dict = {"symbol": sym, "trading_date": d.isoformat()}
        for src, dst in NUMERIC_FIELDS.items():
            v = to_float(row.get(src))
            if v is not None and v < 0:
                report["negative_values"] += 1
                v = None
            rec[dst] = v

        if rec["close"] is None or rec["close"] <= 0:
            report["bad_close"] += 1
            continue

        key = (sym, rec["trading_date"])
        if key in seen:
            report["duplicates"] += 1
        seen[key] = rec

    out = sorted(seen.values(), key=lambda r: r["trading_date"])
    report["rows_out"] = len(out)
    return out, report