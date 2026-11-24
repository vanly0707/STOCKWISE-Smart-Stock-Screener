"""Kiểm tra chất lượng dữ liệu trong SQLite.

Chạy: python -m src.data.check_data
Kết quả dùng cho báo cáo (phần kiểm chứng dữ liệu) và để chọn ngưỡng lọc ở bước chấm điểm.
"""
from __future__ import annotations

import argparse
import statistics
import sys

from ..utils.output import redirect_stdout_to_file
from . import storage

TY = 1e9  # 1 tỷ đồng


def _pct(values: list[float], p: int) -> float:
    if len(values) < 2:
        return values[0] if values else float("nan")
    return statistics.quantiles(values, n=100, method="inclusive")[p - 1]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/stockwise.db")
    ap.add_argument("--window", type=int, default=5)
    ap.add_argument("--out", help="ghi kết quả ra file UTF-8 (tránh lỗi font khi dùng > trong PowerShell)")
    args = ap.parse_args(argv)
    if args.out:
        redirect_stdout_to_file(args.out)

    conn = storage.connect(args.db)
    q = lambda sql, *a: conn.execute(sql, a).fetchall()  # noqa: E731

    st = storage.stats(conn)
    print("=== 1. TỔNG QUAN ===")
    print(f"Mã có dữ liệu: {st['n_symbols']} | bản ghi: {st['n_rows']} | "
          f"số phiên: {st['n_dates']} | từ {st['min_date']} đến {st['max_date']}")
    for r in q("SELECT status, COUNT(*) n FROM collect_status GROUP BY status"):
        print(f"  trạng thái {r['status']}: {r['n']} mã")

    print("\n=== 2. THEO SÀN (số mã trong danh sách / số mã có dữ liệu) ===")
    for r in q("""SELECT s.board, COUNT(*) total,
                         SUM(CASE WHEN d.n > 0 THEN 1 ELSE 0 END) with_data
                  FROM securities s
                  LEFT JOIN (SELECT symbol, COUNT(*) n FROM daily_summary GROUP BY symbol) d
                         ON d.symbol = s.symbol
                  GROUP BY s.board ORDER BY total DESC"""):
        print(f"  {r['board']}: {r['total']} / {r['with_data']}")

    print("\n=== 3. MÃ KHÔNG CÓ DỮ LIỆU (mẫu 15 mã) ===")
    for r in q("""SELECT s.symbol, s.board FROM securities s
                  WHERE s.board = 'HOSE' AND NOT EXISTS (SELECT 1 FROM daily_summary d WHERE d.symbol = s.symbol)
                  ORDER BY s.board, s.symbol LIMIT 15"""):
        print(f"  {r['symbol']} ({r['board']})")

    print("\n=== 4. MÃ KHÔNG NẰM TRONG LƯỢT CẬP NHẬT DANH SÁCH GẦN NHẤT ===")
    print("  (nên chạy sau lượt thu thập toàn thị trường; mã ở đây có thể bị bộ lọc cổ phiếu loại nhầm)")
    stale = q("""SELECT symbol, board, icb_code FROM securities
                 WHERE board = 'HOSE'
                   AND updated_at < (SELECT MAX(updated_at) FROM securities WHERE board = 'HOSE')""")
    for r in stale[:20]:
        print(f"  {r['symbol']} board={r['board']} icb={r['icb_code']}")
    if not stale:
        print("  (không có)")

    print("\n=== 5. SỐ PHIÊN CÓ DỮ LIỆU MỖI MÃ ===")
    sessions = [r["n"] for r in q("SELECT COUNT(*) n FROM daily_summary d JOIN securities s ON s.symbol = d.symbol WHERE s.board = 'HOSE' GROUP BY d.symbol")]
    need = args.window + 1
    buckets = {"≥ 40 phiên": sum(n >= 40 for n in sessions),
               f"{need}–39 phiên": sum(need <= n < 40 for n in sessions),
               f"< {need} phiên (không đủ tính momentum)": sum(n < need for n in sessions)}
    for k, v in buckets.items():
        print(f"  {k}: {v} mã")

    print("\n=== 6. DỮ LIỆU KHỐI NGOẠI THEO SÀN (tỷ lệ bản ghi có giao dịch khối ngoại) ===")
    for r in q("""SELECT s.board, COUNT(*) n,
                         SUM(CASE WHEN COALESCE(d.foreign_buy_value,0)
                                    + COALESCE(d.foreign_sell_value,0) > 0 THEN 1 ELSE 0 END) f
                  FROM daily_summary d JOIN securities s ON s.symbol = d.symbol
                  GROUP BY s.board"""):
        print(f"  {r['board']}: {100 * r['f'] / r['n']:.1f}% ({r['f']}/{r['n']})")

    print("\n=== 7. PHIÊN KHÔNG KHỚP LỆNH (total_match = 0 hoặc rỗng) ===")
    r = q("""SELECT COUNT(*) n, SUM(CASE WHEN COALESCE(total_match,0)=0 THEN 1 ELSE 0 END) z
             FROM daily_summary""")[0]
    print(f"  {r['z']}/{r['n']} bản ghi ({100 * r['z'] / max(r['n'], 1):.1f}%)")

    print(f"\n=== 8. GIÁ TRỊ KHỚP BÌNH QUÂN {args.window} PHIÊN GẦN NHẤT (tỷ đồng/phiên) ===")
    rows = q(f"""WITH r AS (
                    SELECT symbol, total_match_value v,
                           ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trading_date DESC) rn
                    FROM daily_summary)
                 SELECT r.symbol, s.board, AVG(r.v) avg_v
                 FROM r JOIN securities s ON s.symbol = r.symbol
                 WHERE r.rn <= {int(args.window)}
                 GROUP BY r.symbol HAVING COUNT(r.v) = {int(args.window)}""")
    by_board: dict[str, list[float]] = {}
    for r in rows:
        by_board.setdefault(r["board"], []).append(r["avg_v"] / TY)
    print("  Sàn     Số mã    P10     P25     P50     P75     P90")
    for board, vals in sorted(by_board.items()):
        ps = " ".join(f"{_pct(vals, p):7.3f}" for p in (10, 25, 50, 75, 90))
        print(f"  {board:<7} {len(vals):5d} {ps}")
    allv = [r["avg_v"] / TY for r in rows]
    if allv:
        print("  Toàn thị trường:", " ".join(f"P{p}={_pct(allv, p):.3f}" for p in (10, 20, 25, 50)))

    print(f"\n=== 9. TỶ TRỌNG GIÁ TRỊ KHỚP THEO SÀN ({args.window} phiên gần nhất) ===")
    rows = q("""SELECT s.board, SUM(d.total_match_value) v, COUNT(DISTINCT d.symbol) n
                FROM daily_summary d JOIN securities s ON s.symbol = d.symbol
                WHERE d.trading_date IN (SELECT DISTINCT trading_date FROM daily_summary
                                         ORDER BY trading_date DESC LIMIT ?)
                GROUP BY s.board""", int(args.window))
    total = sum((r["v"] or 0) for r in rows)
    for r in sorted(rows, key=lambda r: -(r["v"] or 0)):
        share = 100 * (r["v"] or 0) / total if total else 0
        print(f"  {r['board']}: {(r['v'] or 0) / TY:,.0f} tỷ đồng ({share:.1f}%) | {r['n']} mã")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())