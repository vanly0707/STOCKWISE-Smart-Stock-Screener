"""Ghi kết quả của các script ra file UTF-8.

Lý do: trong Windows PowerShell, `python ... > file.txt` giải mã đầu ra UTF-8 của Python bằng
bảng mã của console (cp437/cp850) nên tiếng Việt trong file bị vỡ ("TỔNG QUAN" thành "Tß╗öNG QUAN").
Dùng tham số --out để Python tự ghi file với encoding UTF-8 chuẩn.
"""
from __future__ import annotations

import atexit
import sys
from pathlib import Path


def redirect_stdout_to_file(path: str) -> None:
    """Từ lúc gọi, mọi lệnh print() được ghi vào `path` (UTF-8); khi thoát sẽ báo ra màn hình."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "w", encoding="utf-8", buffering=1)
    original = sys.stdout
    sys.stdout = f

    def _finish() -> None:
        sys.stdout = original
        f.close()
        print(f"Đã ghi kết quả vào {path}", file=original)

    atexit.register(_finish)