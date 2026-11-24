"""Xác định tập cổ phiếu cần thu thập."""
from __future__ import annotations

import logging
import re

from .cleaning import to_float

log = logging.getLogger(__name__)

EQUITY_SYMBOL = re.compile(r"^[A-Z0-9]{3}$")
EQUITY_BOARDS = {"HOSE", "HNX", "UPCOM"}


def is_equity(item: dict) -> bool:
    """Cổ phiếu = mã 3 ký tự + có mã ngành ICB + không phải chứng quyền + thuộc 3 sàn."""
    symbol = str(item.get("symbol") or "").strip().upper()
    board = str(item.get("board") or "").strip().upper()
    return (
        bool(EQUITY_SYMBOL.match(symbol))
        and bool(item.get("icbCode"))
        and not item.get("cwUnderlyingSymbol")
        and board in EQUITY_BOARDS
    )


def _normalize(item: dict, board_hint: str | None = None) -> dict:
    return {
        "symbol": str(item["symbol"]).strip().upper(),
        "board": item.get("board") or board_hint,
        "icb_code": item.get("icbCode"),
        "listed_share": to_float(item.get("listedShare")),
    }


def get_universe(client, cfg: dict, index_override: str | None = None) -> list[dict]:
    """Lấy danh sách mã. Theo chỉ số: 1 request; theo sàn: 1 request/sàn (+1 request/chỉ số bổ sung)."""
    index = index_override or (cfg.get("index") if cfg.get("mode") == "index" else None)
    found: dict[str, dict] = {}

    if index:
        for item in client.securities_list(index=index):
            if item.get("symbol"):
                rec = _normalize(item)
                found[rec["symbol"]] = rec
        log.info("Tập mã theo chỉ số %s: %d mã", index, len(found))
    else:
        boards = [b.upper() for b in cfg.get("boards", ["HOSE", "HNX", "UPCOM"])]
        allowed = set(boards)
        for board in boards:
            items = client.securities_list(board=board)
            kept = [it for it in items if is_equity(it)]
            log.info("%s: %d mục, giữ %d cổ phiếu", board, len(items), len(kept))
            for item in kept:
                rec = _normalize(item, board)
                found[rec["symbol"]] = rec
        log.info("Tổng số cổ phiếu theo danh sách sàn: %d", len(found))

        # Danh sách theo sàn của SSI có thể thiếu một số mã (ví dụ HPG): bổ sung mã của
        # chỉ số lớn, nhưng chỉ nhận mã thuộc các sàn đang thu thập.
        for idx in cfg.get("include_indexes", []):
            added = []
            for item in client.securities_list(index=idx):
                if not item.get("symbol"):
                    continue
                b = str(item.get("board") or "").upper()
                if not b and len(allowed) == 1:
                    b = next(iter(allowed))
                if b not in allowed:
                    continue
                rec = _normalize(item, b)
                if rec["symbol"] not in found:
                    found[rec["symbol"]] = rec
                    added.append(rec["symbol"])
            log.info("Bổ sung %d mã từ chỉ số %s không có trong danh sách sàn: %s",
                     len(added), idx, added)
        log.info("Tổng số cổ phiếu (%s): %d", ", ".join(boards), len(found))

    return sorted(found.values(), key=lambda r: r["symbol"])