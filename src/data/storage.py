"""Lưu trữ SQLite cho STOCKWISE. Mọi mốc thời gian theo múi giờ Asia/Ho_Chi_Minh (UTC+7)."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SCHEMA = """
CREATE TABLE IF NOT EXISTS securities (
    symbol         TEXT PRIMARY KEY,
    board          TEXT,
    icb_code       TEXT,
    listed_share   REAL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_summary (
    symbol              TEXT NOT NULL,
    trading_date        TEXT NOT NULL,          -- ISO YYYY-MM-DD
    close               REAL NOT NULL,          -- đồng/cổ phiếu
    total_match         REAL,                   -- cổ phiếu
    total_match_value   REAL,                   -- đồng
    foreign_buy_vol     REAL,
    foreign_buy_value   REAL,                   -- đồng
    foreign_sell_vol    REAL,
    foreign_sell_value  REAL,                   -- đồng
    remain_foreign_room REAL,
    total_foreign_room  REAL,
    collected_at        TEXT NOT NULL,          -- thời điểm thu thập (UTC+7)
    PRIMARY KEY (symbol, trading_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_summary(trading_date);

CREATE TABLE IF NOT EXISTS collect_status (
    symbol              TEXT PRIMARY KEY,
    last_trading_date   TEXT,
    last_collected_at   TEXT NOT NULL,
    status              TEXT NOT NULL,          -- ok | empty | error
    note                TEXT
);

CREATE TABLE IF NOT EXISTS collect_runs (
    run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    n_symbols    INTEGER,
    n_ok         INTEGER,
    n_skipped    INTEGER,
    n_error      INTEGER,
    n_rows       INTEGER,
    note         TEXT
);
"""

DAILY_COLUMNS = ("symbol", "trading_date", "close", "total_match", "total_match_value",
                 "foreign_buy_vol", "foreign_buy_value", "foreign_sell_vol",
                 "foreign_sell_value", "remain_foreign_room", "total_foreign_room")


def now_vn() -> datetime:
    return datetime.now(VN_TZ)


def now_vn_iso() -> str:
    return now_vn().isoformat(timespec="seconds")


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def upsert_securities(conn: sqlite3.Connection, items: list[dict]) -> None:
    ts = now_vn_iso()
    conn.executemany(
        """INSERT INTO securities(symbol, board, icb_code, listed_share, updated_at)
           VALUES(:symbol, :board, :icb_code, :listed_share, :ts)
           ON CONFLICT(symbol) DO UPDATE SET board=excluded.board,
               icb_code=excluded.icb_code, listed_share=excluded.listed_share,
               updated_at=excluded.updated_at""",
        [{**it, "ts": ts} for it in items],
    )
    conn.commit()


def upsert_daily(conn: sqlite3.Connection, rows: list[dict], collected_at: str | None = None) -> int:
    """Ghi (hoặc cập nhật) bản ghi theo khóa (mã, ngày). Trả về số bản ghi đã ghi."""
    if not rows:
        return 0
    ts = collected_at or now_vn_iso()
    cols = ", ".join(DAILY_COLUMNS)
    params = ", ".join(f":{c}" for c in DAILY_COLUMNS)
    updates = ", ".join(f"{c}=excluded.{c}" for c in DAILY_COLUMNS[2:])
    conn.executemany(
        f"""INSERT INTO daily_summary({cols}, collected_at) VALUES({params}, :collected_at)
            ON CONFLICT(symbol, trading_date) DO UPDATE SET {updates},
                collected_at=excluded.collected_at""",
        [{**{c: r.get(c) for c in DAILY_COLUMNS}, "collected_at": ts} for r in rows],
    )
    conn.commit()
    return len(rows)


def get_status(conn: sqlite3.Connection, symbol: str) -> dict | None:
    row = conn.execute("SELECT * FROM collect_status WHERE symbol=?", (symbol,)).fetchone()
    return dict(row) if row else None


def set_status(conn: sqlite3.Connection, symbol: str, status: str,
               last_trading_date: str | None = None, note: str = "") -> None:
    conn.execute(
        """INSERT INTO collect_status(symbol, last_trading_date, last_collected_at, status, note)
           VALUES(?, ?, ?, ?, ?)
           ON CONFLICT(symbol) DO UPDATE SET
               last_trading_date=COALESCE(excluded.last_trading_date, last_trading_date),
               last_collected_at=excluded.last_collected_at,
               status=excluded.status, note=excluded.note""",
        (symbol, last_trading_date, now_vn_iso(), status, note[:300]),
    )
    conn.commit()


def start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute("INSERT INTO collect_runs(started_at) VALUES(?)", (now_vn_iso(),))
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, *, n_symbols: int, n_ok: int,
               n_skipped: int, n_error: int, n_rows: int, note: str = "") -> None:
    conn.execute(
        """UPDATE collect_runs SET finished_at=?, n_symbols=?, n_ok=?, n_skipped=?,
               n_error=?, n_rows=?, note=? WHERE run_id=?""",
        (now_vn_iso(), n_symbols, n_ok, n_skipped, n_error, n_rows, note, run_id),
    )
    conn.commit()


def stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """SELECT COUNT(DISTINCT symbol) AS n_symbols, COUNT(*) AS n_rows,
                  COUNT(DISTINCT trading_date) AS n_dates,
                  MIN(trading_date) AS min_date, MAX(trading_date) AS max_date
           FROM daily_summary"""
    ).fetchone()
    return dict(row)