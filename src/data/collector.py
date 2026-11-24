"""Thu thập dữ liệu securitiesSummary của SSI vào SQLite.

Chạy:
    python -m src.data.collector --limit 5        # thử nhanh với 5 mã
    python -m src.data.collector --index VN30     # chỉ một chỉ số
    python -m src.data.collector                  # toàn bộ cổ phiếu (theo settings.yaml)
    python -m src.data.collector --force          # bỏ qua dấu "đã thu thập hôm nay"

Có checkpoint theo từng mã: nếu bị ngắt (hết quota, mất mạng), chạy lại sẽ tiếp tục
từ chỗ dở, không lấy lại những mã đã xong trong ngày.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path

import yaml

from ..ssi_client.auth import SSIAuthError
from ..ssi_client.rest import SSIApiError, SSIClient, SSIRateLimitError
from . import storage
from .cleaning import clean_summary_rows
from .universe import get_universe

log = logging.getLogger(__name__)
DEFAULT_CONFIG = "config/settings.yaml"


def load_config(path: str = DEFAULT_CONFIG) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def compute_start(status: dict | None, end: date, backfill_days: int, overlap_days: int) -> date:
    """Ngày bắt đầu lấy dữ liệu cho một mã."""
    if status and status.get("last_trading_date"):
        return date.fromisoformat(status["last_trading_date"]) - timedelta(days=overlap_days)
    return end - timedelta(days=backfill_days)



def last_expected_session(today: date) -> date:
    """Phiên gần nhất có thể đã có dữ liệu: lùi qua thứ Bảy, Chủ nhật (ngày lễ chưa xét)."""
    d = today
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


MARKET_CLOSE = dtime(15, 30)   # sau giờ này dữ liệu cuối ngày mới đầy đủ


def _parse_ts(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=storage.VN_TZ)


def collected_today(status: dict | None, today: date, now: datetime | None = None) -> bool:
    """Bỏ qua mã nếu dữ liệu đã đủ cho phiên gần nhất.

    Cần cả hai: (1) có dữ liệu đến phiên gần nhất; (2) nếu đã qua 15:30 của phiên đó thì
    lần thu thập phải diễn ra sau 15:30, tránh giữ dữ liệu lấy giữa phiên.
    """
    if not status or status.get("status") != "ok":
        return False
    expected = last_expected_session(today)
    last = status.get("last_trading_date")
    if not (last and str(last)[:10] >= expected.isoformat()):
        return False
    now = now or storage.now_vn()
    cutoff = datetime.combine(expected, MARKET_CLOSE, tzinfo=storage.VN_TZ)
    if now < cutoff:
        return True
    at = _parse_ts(status.get("last_collected_at"))
    return at is not None and at >= cutoff


def run(cfg: dict, *, client=None, limit: int | None = None,
        index: str | None = None, force: bool = False) -> dict:
    ccfg = cfg["collect"]
    client = client or SSIClient(min_interval=ccfg.get("min_interval", 0.3))
    conn = storage.connect(ccfg["db_path"])
    now = storage.now_vn()
    today = now.date()
    run_id = storage.start_run(conn)
    totals = {"n_symbols": 0, "n_ok": 0, "n_skipped": 0, "n_error": 0, "n_rows": 0}
    n_empty = 0   # mã gọi API thành công nhưng không có bản ghi hợp lệ (đã tính trong n_ok)
    note = "hoàn tất"

    try:
        universe = get_universe(client, cfg["universe"], index_override=index)
        if limit:
            universe = universe[:limit]
        storage.upsert_securities(conn, universe)
        totals["n_symbols"] = len(universe)

        consecutive_errors = 0
        started = time.monotonic()
        for i, sec in enumerate(universe, 1):
            sym = sec["symbol"]
            status = storage.get_status(conn, sym)
            if not force and collected_today(status, today, now):
                totals["n_skipped"] += 1
                continue

            start = compute_start(status, today, ccfg["backfill_days"], ccfg["overlap_days"])
            try:
                raw = client.securities_summary(sym, start, today)
            except SSIRateLimitError as exc:
                note = f"dừng do quota: {exc}"
                log.error(note)
                break
            except SSIAuthError:
                raise
            except Exception as exc:  # noqa: BLE001 - một mã lỗi không làm hỏng cả lượt
                totals["n_error"] += 1
                consecutive_errors += 1
                storage.set_status(conn, sym, "error", note=f"{type(exc).__name__}: {exc}")
                log.warning("Lỗi mã %s: %s", sym, exc)
                if consecutive_errors >= ccfg.get("max_consecutive_errors", 10):
                    note = f"dừng do {consecutive_errors} lỗi liên tiếp"
                    log.error(note)
                    break
                continue

            consecutive_errors = 0
            rows, report = clean_summary_rows(raw, sym)
            if report["rows_in"] != report["rows_out"]:
                log.info("%s: %s", sym, report)
            if rows:
                totals["n_rows"] += storage.upsert_daily(conn, rows)
                storage.set_status(conn, sym, "ok", last_trading_date=rows[-1]["trading_date"])
            else:
                storage.set_status(conn, sym, "empty", note="không có bản ghi hợp lệ")
                n_empty += 1
            totals["n_ok"] += 1

            if i % 25 == 0:
                rate = i / max(time.monotonic() - started, 1e-9)
                log.info("Tiến độ %d/%d mã (%.1f mã/giây)", i, len(universe), rate)

    except SSIAuthError as exc:
        note = f"dừng do lỗi xác thực: {exc}"
        log.error(note)
    finally:
        storage.finish_run(conn, run_id, note=note, **totals)

    db = storage.stats(conn)
    result = {
        **totals,                                  # số liệu của LƯỢT CHẠY này
        "n_empty": n_empty,
        "note": note,
        "db_symbols_with_data": db["n_symbols"],   # số liệu của TOÀN BỘ CSDL
        "db_rows": db["n_rows"],
        "n_dates": db["n_dates"],
        "min_date": db["min_date"],
        "max_date": db["max_date"],
    }
    conn.close()
    return result


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Thu thập dữ liệu SSI cho STOCKWISE")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--limit", type=int, help="chỉ thu thập N mã đầu tiên (để thử)")
    parser.add_argument("--index", help="chỉ thu thập theo chỉ số, ví dụ VN30, VN100")
    parser.add_argument("--force", action="store_true", help="bỏ qua dấu đã thu thập hôm nay")
    args = parser.parse_args(argv)

    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler("logs/collector.log", encoding="utf-8")],
    )

    result = run(load_config(args.config), limit=args.limit, index=args.index, force=args.force)
    log.info("KẾT QUẢ: %s", result)
    return 0 if result["n_error"] == 0 and result["note"] == "hoàn tất" else 1


if __name__ == "__main__":
    raise SystemExit(main())