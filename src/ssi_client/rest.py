"""Client REST cho SSI FastConnect Market Data (chỉ GET, chỉ đọc dữ liệu)."""
import logging
import time
from datetime import date

import requests

from .auth import BASE_URL, get_auth_headers, invalidate_token

log = logging.getLogger(__name__)

SECURITIES_BY_BOARD = "/api/v3/data/securitiesByBoard"
SECURITIES_SUMMARY = "/api/v3/data/securitiesSummary"
OHLC = "/api/v3/data/ohlc"


class SSIApiError(Exception):
    """Lỗi gọi API SSI (không chứa khóa hay token)."""


class SSIRateLimitError(SSIApiError):
    """Quota request sắp hết, dừng để không vượt giới hạn."""


def _fmt_date(d: date) -> str:
    return d.strftime("%Y/%m/%d")  # định dạng SSI yêu cầu


def _unwrap(body):
    """Tài liệu bọc dữ liệu trong khóa 'response'; xử lý cả hai dạng."""
    if isinstance(body, dict) and "response" in body:
        return body["response"]
    return body


def _parse_reset(raw: str | None) -> float | None:
    """Đổi header X-RATELIMIT-RESET thành epoch giây.

    Định dạng chưa được tài liệu mô tả rõ nên đoán theo độ lớn:
    epoch mili giây, epoch giây, hoặc số giây còn lại. Trả None nếu không hiểu.
    """
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    if v > 1e12:
        return v / 1000
    if v > 1e9:
        return v
    return time.time() + v


class SSIClient:
    def __init__(self, min_interval: float = 0.3, max_retries: int = 4,
                 low_quota_guard: int = 5, timeout: int = 20):
        self.session = requests.Session()
        self.min_interval = min_interval      # giãn cách tối thiểu giữa hai request (giây)
        self.max_retries = max_retries
        self.low_quota_guard = low_quota_guard
        self.timeout = timeout
        self.remaining: int | None = None     # quota còn lại theo header gần nhất
        self.rate_limit: str | None = None    # giá trị thô X-RATELIMIT-LIMIT
        self.rate_reset: str | None = None    # giá trị thô X-RATELIMIT-RESET
        self._reset_at: float | None = None   # epoch giây dự kiến reset
        self._last_call = 0.0

    # ---------- nội bộ ----------
    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)

    def _update_quota(self, resp: requests.Response) -> None:
        self.rate_limit = resp.headers.get("X-RATELIMIT-LIMIT", self.rate_limit)
        raw_reset = resp.headers.get("X-RATELIMIT-RESET")
        if raw_reset:
            self.rate_reset = raw_reset
            self._reset_at = _parse_reset(raw_reset)
        try:
            self.remaining = int(resp.headers["X-RATELIMIT-REMAINING"])
        except (KeyError, ValueError):
            pass

    def _check_quota(self) -> None:
        """Nếu quota sắp hết thì chờ hồi phục; chỉ dừng hẳn khi phải chờ quá lâu."""
        if self.remaining is None or self.remaining > self.low_quota_guard:
            return
        if self._reset_at is not None:
            wait = self._reset_at - time.time()
            if wait > 60.0:
                raise SSIRateLimitError(
                    f"Quota còn {self.remaining} request, cần chờ {wait:.0f}s mới được cấp lại"
                )
            wait = max(wait, 0.0)
        else:
            wait = 2.0  # SSI không gửi header RESET; quota có vẻ hồi phục nhanh
        log.info("Quota còn %s, chờ %.1fs", self.remaining, wait)
        time.sleep(wait)
        self.remaining = None

    @staticmethod
    def _error_detail(resp: requests.Response) -> str:
        try:
            err = _unwrap(resp.json())
            return f"code={err.get('code')} msg={err.get('msg')}"
        except (ValueError, AttributeError):
            return "phản hồi không phải JSON"

    def _retry_wait(self, resp: requests.Response, attempt: int) -> float:
        """Thời gian chờ trước khi thử lại; ưu tiên header RESET khi gặp 429."""
        if resp.status_code == 429:
            reset_at = _parse_reset(resp.headers.get("X-RATELIMIT-RESET"))
            if reset_at is not None:
                return min(max(reset_at - time.time(), 1.0), 60.0)
        return min(2.0 ** attempt, 30.0)

    def _get(self, path: str, params: dict):
        url = f"{BASE_URL}{path}"
        relogged = False
        for attempt in range(1, self.max_retries + 1):
            self._check_quota()
            self._throttle()
            headers = {"Content-Type": "application/json", "Accept-Language": "vi",
                       **get_auth_headers()}
            try:
                resp = self.session.get(url, params=params, headers=headers,
                                        timeout=self.timeout)
            except requests.RequestException as exc:
                log.warning("Lỗi mạng %s (lần %d/%d)", type(exc).__name__,
                            attempt, self.max_retries)
                time.sleep(min(2.0 ** attempt, 30.0))
                continue

            self._last_call = time.monotonic()
            self._update_quota(resp)

            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    raise SSIApiError(f"{path}: phản hồi 200 nhưng không phải JSON") from None
            if resp.status_code == 401 and not relogged:
                log.warning("Token bị từ chối (401), xin token mới")
                invalidate_token()
                relogged = True
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = self._retry_wait(resp, attempt)
                log.warning("HTTP %d tại %s, chờ %.1fs (lần %d/%d)",
                            resp.status_code, path, wait, attempt, self.max_retries)
                time.sleep(wait)
                continue
            raise SSIApiError(f"HTTP {resp.status_code} tại {path}: "
                              f"{self._error_detail(resp)}")
        raise SSIApiError(f"{path}: hết số lần thử")

    # ---------- API công khai ----------
    def securities_list(self, *, board: str | None = None,
                        index: str | None = None) -> list[dict]:
        """Danh sách chứng khoán theo sàn (HOSE/HNX/UPCOM) hoặc theo chỉ số (VN30, VN100...).

        SSI chỉ cho phép đúng một trong hai tham số.
        """
        if (board is None) == (index is None):
            raise ValueError("Chỉ truyền đúng một trong hai tham số: board hoặc index")
        params = {"board": board} if board else {"index": index}
        data = _unwrap(self._get(SECURITIES_BY_BOARD, params))
        if not isinstance(data, list):
            raise SSIApiError("securitiesByBoard: định dạng phản hồi không phải danh sách")
        return data

    def securities_summary(self, symbol: str, start: date, end: date,
                           page_size: int = 100, max_pages: int = 50) -> list[dict]:
        """Tổng hợp giao dịch theo ngày của một mã (có phân trang tự động)."""
        rows: list[dict] = []
        for page in range(1, max_pages + 1):
            body = _unwrap(self._get(SECURITIES_SUMMARY, {
                "symbol": symbol, "from": _fmt_date(start), "to": _fmt_date(end),
                "pageIndex": page, "pageSize": page_size,
            }))
            batch = body.get("data") or []
            rows.extend(batch)
            pages = body.get("pagesCount")
            if not batch or (pages is not None and page >= pages):
                break
        return rows

    def ohlc_daily(self, symbol: str, start: date, end: date,
                   page_size: int = 100, max_pages: int = 50) -> list[dict]:
        """Nến ngày (OHLCV) của một mã."""
        rows: list[dict] = []
        for page in range(1, max_pages + 1):
            body = _unwrap(self._get(OHLC, {
                "symbol": symbol, "from": _fmt_date(start), "to": _fmt_date(end),
                "timeFrame": "1d", "pageIndex": page, "pageSize": page_size,
            }))
            batch = body.get("data") or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
        return rows