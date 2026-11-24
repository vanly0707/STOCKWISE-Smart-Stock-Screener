"""Kiểm thử làm sạch dữ liệu, dùng bản ghi thật của VCB (SSI securitiesSummary)."""
from datetime import date

from src.data.cleaning import clean_summary_rows, parse_date, to_float

VCB_ROWS = [  # thứ tự lộn xộn như phản hồi thật
    {"symbol": "VCB", "tradingDate": "2026/11/09", "close": "53600", "totalMatch": "2985600",
     "totalMatchValue": "160108690000", "totalForeignBuy": "234110",
     "totalForeignBuyValue": "12560938000", "totalForeignSell": "782961",
     "totalForeignSellValue": "42015259600"},
    {"symbol": "VCB", "tradingDate": "2026/11/06", "close": "53600", "totalMatch": "5202300",
     "totalMatchValue": "278957410000", "totalForeignBuy": "28500",
     "totalForeignBuyValue": "1529800000", "totalForeignSell": "2093700",
     "totalForeignSellValue": "112335640000"},
    {"symbol": "VCB", "tradingDate": "2026/11/17", "close": "52100", "totalMatch": "7003000",
     "totalMatchValue": "367514810000", "totalForeignBuy": "73895",
     "totalForeignBuyValue": "3880896000", "totalForeignSell": "2024589",
     "totalForeignSellValue": "106311816400"},
    {"symbol": "VCB", "tradingDate": "2026/11/13", "close": "53800", "totalMatch": "1760200",
     "totalMatchValue": "94707520000", "totalForeignBuy": "334000",
     "totalForeignBuyValue": "17988730000", "totalForeignSell": "135476",
     "totalForeignSellValue": "7293033300"},
]


def test_to_float():
    assert to_float("53600") == 53600.0
    assert to_float("1,234.5") == 1234.5
    assert to_float(7) == 7.0
    for bad in (None, "", "-", "abc", "nan", float("inf")):
        assert to_float(bad) is None


def test_parse_date_formats():
    assert parse_date("2026/11/09") == date(2026, 11, 9)
    assert parse_date("2026-11-09") == date(2026, 11, 9)
    assert parse_date("09/11/2026") == date(2026, 11, 9)
    assert parse_date("không phải ngày") is None
    assert parse_date(None) is None


def test_sorted_ascending_and_typed():
    rows, rep = clean_summary_rows(VCB_ROWS)
    assert [r["trading_date"] for r in rows] == ["2026-11-06", "2026-11-09",
                                                  "2026-11-13", "2026-11-17"]
    assert rows[1]["close"] == 53600.0
    assert rep["rows_in"] == 4 and rep["rows_out"] == 4


def test_units_match_value_consistent_with_price_times_volume():
    # Giá trị khớp (đồng) xấp xỉ giá (đồng) x khối lượng: kiểm tra đơn vị
    rows, _ = clean_summary_rows(VCB_ROWS)
    r = rows[1]
    approx = r["close"] * r["total_match"]
    assert abs(r["total_match_value"] - approx) / approx < 0.01


def test_net_foreign_value_vcb_9_nov():
    rows, _ = clean_summary_rows(VCB_ROWS)
    r = next(x for x in rows if x["trading_date"] == "2026-11-09")
    assert r["foreign_buy_value"] - r["foreign_sell_value"] == -29454321600.0


def test_duplicates_keep_last():
    dup = dict(VCB_ROWS[0], close="54000")
    rows, rep = clean_summary_rows(VCB_ROWS + [dup])
    assert rep["duplicates"] == 1
    assert len(rows) == 4
    assert next(r for r in rows if r["trading_date"] == "2026-11-09")["close"] == 54000.0


def test_bad_rows_are_dropped_and_counted():
    bad = [
        {"symbol": "AAA", "tradingDate": "", "close": "10000"},          # ngày rỗng
        {"symbol": "AAA", "tradingDate": "2026/11/09", "close": "0"},    # giá 0
        {"symbol": "AAA", "tradingDate": "2026/11/10", "close": None},   # thiếu giá
        {"symbol": "", "tradingDate": "2026/11/10", "close": "10000"},   # thiếu mã
    ]
    rows, rep = clean_summary_rows(bad)
    assert rows == []
    assert rep["bad_date"] == 1 and rep["bad_close"] == 2 and rep["missing_symbol"] == 1


def test_symbol_fallback_and_negative_values_become_none():
    raw = [{"tradingDate": "2026/11/09", "close": "10000", "totalForeignBuyValue": "-5",
            "totalForeignSellValue": "", "totalMatchValue": "100"}]
    rows, rep = clean_summary_rows(raw, symbol="abc")
    assert rows[0]["symbol"] == "ABC"
    assert rows[0]["foreign_buy_value"] is None      # âm -> None, không bịa số
    assert rows[0]["foreign_sell_value"] is None     # rỗng -> None
    assert rows[0]["total_match_value"] == 100.0
    assert rep["negative_values"] == 1