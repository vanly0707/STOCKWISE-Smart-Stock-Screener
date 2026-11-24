"""Lấy, cache và làm mới access token SSI FastConnect.

Chỉ dùng cho dữ liệu thị trường (không cần OTP, không dùng Private Key, không giao dịch).
Thứ tự: dùng token còn hạn -> refresh bằng refresh token -> xin token mới bằng apiKey/apiSecret.
"""
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

BASE_URL = os.getenv("SSI_BASE_URL", "https://api.ssi.com.vn")
TOKEN_URL = f"{BASE_URL}/api/v3/auth/token"
REFRESH_URL = f"{BASE_URL}/api/v3/auth/refresh"
CACHE_FILE = Path(".token_cache.json")
SAFETY_MARGIN_MS = 60_000  # coi token là hết hạn sớm 60 giây
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class SSIAuthError(Exception):
    """Lỗi xác thực SSI (không bao giờ chứa khóa bí mật)."""


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_ms(ts: int | float) -> int:
    """Chuẩn hóa epoch về mili giây (SSI có thể trả về giây hoặc mili giây)."""
    ts = int(ts)
    return ts * 1000 if ts < 100_000_000_000 else ts


def _load_cache() -> dict | None:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_cache(data: dict) -> None:
    CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
    try:
        CACHE_FILE.chmod(0o600)
    except OSError:
        pass  # Windows có thể không hỗ trợ


def invalidate_token() -> None:
    """Xóa cache để lần get_token() sau xin token mới (dùng khi API trả 401)."""
    CACHE_FILE.unlink(missing_ok=True)


def _post_for_token(url: str, payload: dict, what: str) -> dict:
    """Gọi endpoint auth và chuẩn hóa lỗi. Không bao giờ in khóa/token."""
    try:
        resp = requests.post(url, json=payload, timeout=15)
    except requests.RequestException as exc:
        raise SSIAuthError(
            f"{what}: không kết nối được tới SSI ({type(exc).__name__})"
        ) from None

    if resp.status_code != 200:
        try:
            body = resp.json()
            err = body.get("response", body)
            detail = f"code={err.get('code')} msg={err.get('msg')}"
        except (ValueError, AttributeError):
            detail = "phản hồi không phải JSON"
        raise SSIAuthError(f"{what} thất bại (HTTP {resp.status_code}): {detail}")

    body = resp.json()
    data = body.get("response", body)  # tài liệu hiển thị cả dạng bọc và không bọc
    if "accessToken" not in data:
        raise SSIAuthError(f"{what}: phản hồi không có accessToken")

    # Chuẩn hóa mốc hết hạn về mili giây để so sánh nhất quán
    for key in ("expiresAt", "refreshExpiresAt"):
        if key in data:
            data[key] = _to_ms(data[key])

    log.info(
        "%s thành công, còn %s request trong chu kỳ",
        what,
        resp.headers.get("X-RATELIMIT-REMAINING", "?"),
    )
    return data


def _request_new_token() -> dict:
    api_key = os.getenv("SSI_API_KEY")
    api_secret = os.getenv("SSI_API_SECRET")
    if not api_key or not api_secret:
        raise SSIAuthError("Thiếu SSI_API_KEY hoặc SSI_API_SECRET trong file .env")
    return _post_for_token(
        TOKEN_URL, {"apiKey": api_key, "apiSecret": api_secret}, "auth/token"
    )


def _refresh(cached: dict) -> dict | None:
    """Thử làm mới bằng refresh token; trả None nếu không thể."""
    rt = cached.get("refreshToken")
    if not rt or cached.get("refreshExpiresAt", 0) - SAFETY_MARGIN_MS <= _now_ms():
        return None
    try:
        return _post_for_token(REFRESH_URL, {"refreshToken": rt}, "auth/refresh")
    except SSIAuthError as exc:
        log.warning("Refresh lỗi, sẽ xin token mới: %s", exc)
        return None


def get_token() -> dict:
    cached = _load_cache()
    if cached and cached.get("expiresAt", 0) - SAFETY_MARGIN_MS > _now_ms():
        return cached                      # 1. token còn hạn
    if cached:
        data = _refresh(cached)            # 2. thử refresh
        if data:
            _save_cache(data)
            return data
    data = _request_new_token()            # 3. xin token mới
    _save_cache(data)
    return data


def get_auth_headers() -> dict:
    t = get_token()
    return {"Authorization": f"{t.get('tokenType', 'Bearer')} {t['accessToken']}"}


if __name__ == "__main__":
    # Kiểm tra nhanh: python -m src.ssi_client.auth  (KHÔNG in token)
    logging.basicConfig(level=logging.INFO)
    t = get_token()
    exp = datetime.fromtimestamp(t["expiresAt"] / 1000, VN_TZ)
    print("OK. Token hết hạn lúc:", exp.strftime("%d/%m/%Y %H:%M:%S (UTC+7)"))