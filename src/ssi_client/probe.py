"""Thăm dò schema và quota thật của SSI: python -m src.ssi_client.probe

Chỉ in dữ liệu thị trường công khai, không in khóa hay token.
Dùng khoảng 8-10 request. Kết quả thô được lưu vào data/raw/ (đã bị .gitignore chặn).
"""
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .rest import SSIClient

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
RAW_DIR = Path("data/raw")
KEY_FIELDS = ["symbol", "tradingDate", "close", "totalMatch", "totalMatchValue",
              "totalForeignBuy", "totalForeignBuyValue",
              "totalForeignSell", "totalForeignSellValue"]


def _save(name: str, payload) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")


def _print_quota(client: SSIClient, label: str) -> None:
    print(f"[Quota {label}] limit={client.rate_limit} | "
          f"remaining={client.remaining} | reset(raw)={client.rate_reset}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    client = SSIClient()
    end = datetime.now(VN_TZ).date()
    start = end - timedelta(days=21)

    # 1. Danh sách mã theo chỉ số
    for idx in ("VN30", "VN100"):
        try:
            members = client.securities_list(index=idx)
        except Exception as exc:  # noqa: BLE001 - thăm dò, in lỗi rồi đi tiếp
            print(f"\n{idx}: LỖI {exc}")
            continue
        _save(f"probe_{idx.lower()}_members.json", members)
        print(f"\n{idx}: {len(members)} mã")
    _print_quota(client, "sau danh sách chỉ số")

    # 2. Quy mô từng sàn và dấu hiệu để lọc cổ phiếu
    for board in ("HOSE", "HNX", "UPCOM"):
        try:
            items = client.securities_list(board=board)
        except Exception as exc:  # noqa: BLE001
            print(f"\n{board}: LỖI {exc}")
            continue
        _save(f"probe_board_{board.lower()}.json", items)
        n_cw = sum(1 for r in items if r.get("cwUnderlyingSymbol"))
        n_icb = sum(1 for r in items if r.get("icbCode"))
        print(f"\n{board}: {len(items)} mã | có cwUnderlyingSymbol: {n_cw} "
              f"| có icbCode: {n_icb}")
        print("  Độ dài mã:", dict(Counter(len(str(r.get('symbol', ''))) for r in items)))
        if items:
            print("  Mẫu:", {k: items[0].get(k) for k in
                             ("symbol", "board", "lotSize", "listedShare", "icbCode")})
    _print_quota(client, "sau danh sách sàn")

    # 3. Tổng hợp giao dịch (nguồn của 3 yếu tố)
    for sym in ("VCB", "FPT", "HPG"):
        try:
            rows = client.securities_summary(sym, start, end)
        except Exception as exc:  # noqa: BLE001
            print(f"\n{sym}: LỖI {exc}")
            continue
        _save(f"probe_summary_{sym}.json", rows)
        print(f"\n=== {sym}: {len(rows)} bản ghi từ {start} đến {end} ===")
        for r in rows[:2] + rows[-2:]:
            print({k: r.get(k) for k in KEY_FIELDS})
        missing = [k for k in KEY_FIELDS if rows and k not in rows[0]]
        if missing:
            print("THIẾU trường:", missing)

    _print_quota(client, "cuối")


if __name__ == "__main__":
    main()