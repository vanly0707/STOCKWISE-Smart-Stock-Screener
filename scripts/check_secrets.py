"""Quét repo tìm khóa/token bị lộ trước khi nộp.

Chạy:  python scripts/check_secrets.py
Thoát mã 1 nếu phát hiện. Kiểm tra: (1) .env / file khóa có bị theo dõi bởi git không,
(2) chuỗi giống khóa trong mã nguồn, cấu hình, log, README, (3) .gitignore có chặn .env, db, logs.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}
TEXT_EXT = {".py", ".yaml", ".yml", ".json", ".md", ".txt", ".toml", ".cfg", ".ini", ".env",
            ".log", ".sql", ".ps1", ".sh", ""}
PATTERNS = {
    "gán khóa/bí mật dạng chuỗi dài": re.compile(
        r"""(?i)(secret|consumer[_-]?secret|consumerSecret|api[_-]?key|password|token)\s*[:=]\s*['"]?[A-Za-z0-9_\-+/=.]{16,}"""),
    "Authorization Bearer": re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-.=]{20,}"),
    "JWT": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "UUID (có thể là consumerID/secret)": re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
}
MUST_IGNORE = [".env", "logs", "data", ".venv"]


def git(*args: str) -> list[str]:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
        return [x for x in out.stdout.splitlines() if x]
    except (OSError, subprocess.CalledProcessError):
        return []


def is_ignored(path: Path) -> bool:
    """True nếu git bỏ qua file này (nằm trong .gitignore). Không có git thì coi như chưa bị bỏ qua."""
    try:
        r = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=ROOT)
        return r.returncode == 0
    except OSError:
        return False


def main() -> int:
    problems: list[str] = []

    tracked = git("ls-files")
    for f in tracked:
        name = Path(f).name.lower()
        if name == ".env" or name.endswith((".pem", ".key")) or name.endswith(".db"):
            problems.append(f"Tệp nhạy cảm đang được git theo dõi: {f}")

    for name in (".token_cache.json",):
        if (ROOT / name).exists() and not is_ignored(ROOT / name):
            problems.append(f"{name} tồn tại nhưng chưa được .gitignore chặn")

    gi = ROOT / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.exists() else ""
    for item in MUST_IGNORE:
        if not re.search(rf"(^|/){re.escape(item)}(/|\s|$)", text, re.M):
            problems.append(f".gitignore chưa chặn '{item}'")

    for p in ROOT.rglob("*"):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in TEXT_EXT or p.stat().st_size > 2_000_000:
            continue
        if p.name == "check_secrets.py":
            continue
        if is_ignored(p):      # file cục bộ đã được .gitignore chặn (.env, token cache...) là hợp lệ
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pat in PATTERNS.items():
            m = pat.search(body)
            if m and p.name != ".env.example":
                line = body[:m.start()].count("\n") + 1
                problems.append(f"{p.relative_to(ROOT)}:{line}: {label}")
                break

    if problems:
        print("PHÁT HIỆN VẤN ĐỀ:")
        for x in problems:
            print(" -", x)
        print("\nNếu khóa đã lên git: đổi (rotate) khóa ngay, rồi xóa khỏi lịch sử. Chỉ xóa file là chưa đủ.")
        return 1
    print("Không phát hiện khóa bị lộ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())