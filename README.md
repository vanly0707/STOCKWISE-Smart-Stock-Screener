# STOCKWISE – Smart Stock Screener

Công cụ sàng lọc và xếp hạng cổ phiếu **HOSE** theo ba yếu tố (động lượng, thanh khoản, dòng tiền khối ngoại) từ dữ liệu **SSI FastConnect API**. Đồ án cá nhân cuối kỳ môn *Gói phần mềm ứng dụng cho tài chính 1* (UEL).

> **Miễn trừ:** STOCKWISE là công cụ phân tích học thuật, không phải khuyến nghị đầu tư. Điểm số là xếp hạng tương đối, không dự báo lợi nhuận. Ứng dụng không đặt lệnh thật.
>
> **Nguồn dữ liệu:** SSI FastConnect API 

## Kiến trúc

```
SSI FastConnect API ─> src/ssi_client (xác thực, giới hạn tốc độ)
        └─> src/data (collector, cleaning, universe) ─> SQLite (data/stockwise.db)
                └─> src/finance (factors, scoring, sensitivity, outofsample)
                        └─> src/app (services -> Streamlit dashboard)
```

## Cài đặt

```
python -m venv .venv
.venv\Scripts\activate            # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
```

## Cấu hình

1. **Khóa SSI** (không đưa vào git): chép `.env.example` thành `.env` rồi điền `SSI_API_KEY` và
   `SSI_API_SECRET` (lấy từ tài khoản SSI FastConnect). `SSI_BASE_URL` là tùy chọn, mặc định
   `https://api.ssi.com.vn`. Token được cache ở `.token_cache.json` (đã bị `.gitignore` chặn).
2. **Tham số** trong `config/settings.yaml`:
   - `universe`: phạm vi cổ phiếu (`boards: [HOSE]`, bổ sung thành viên VN100 còn thiếu).
   - `collect`: `backfill_days` (số ngày lấy lần đầu), `overlap_days`, `min_interval` (giãn cách gọi API).
   - `scoring`: `window` (5/10/20 phiên), `min_avg_value` (ngưỡng thanh khoản, đồng/phiên),
     `min_traded_sessions`, `max_daily_move` (ngưỡng nghi điều chỉnh giá; HOSE biên ±7%).

## Chạy

```
python -m src.data.collector            # thu thập dữ liệu (có checkpoint, chạy lại an toàn)
python -m src.data.check_data           # kiểm tra chất lượng dữ liệu
python -m src.finance.run_ranking       # xếp hạng trên dòng lệnh
python -m src.finance.sensitivity       # độ nhạy trọng số/cửa sổ/ngưỡng
python -m src.finance.outofsample       # kiểm tra ngoài mẫu (IC Spearman)
streamlit run src/app/main.py           # dashboard
python -m pytest -q                     # kiểm thử
python scripts/check_secrets.py         # quét khóa bị lộ trước khi nộp
```

Thời gian hiển thị theo UTC+7. Collector lấy dữ liệu cuối ngày: chạy sau 15:30 để có phiên mới nhất.

## Phương pháp (tóm tắt)

Với cửa sổ N phiên của **thị trường**:
- Động lượng = close[T] / close[T−N] − 1
- Thanh khoản = Σ giá trị khớp trong cửa sổ / N (phiên không giao dịch tính 0)
- Khối ngoại = (Σ mua NN − Σ bán NN) / Σ giá trị khớp
- Mỗi yếu tố đổi sang thứ hạng phần trăm 0–100, điểm tổng = trung bình có trọng số (mặc định bằng nhau).
- Loại mã: thanh khoản dưới ngưỡng, giao dịch quá ít phiên, thiếu lịch sử, biến động giá bất thường.

## Giới hạn

- Chỉ HOSE; dữ liệu cuối ngày, không phải thời gian thực.
- Lịch sử khoảng một năm; giá từ SSI có thể chưa điều chỉnh cổ tức/chia tách, bộ lọc giá nhảy chỉ là biện pháp giảm nhẹ.
- Điểm là xếp hạng tương đối trong rổ đủ điều kiện; kiểm tra ngoài mẫu trên mẫu ngắn chỉ mang tính tham khảo.
- Chưa tính phí giao dịch, thuế, trượt giá; không phải mô hình dự báo hay chiến lược giao dịch.
- Ngày lễ chưa được xử lý riêng trong checkpoint (chỉ làm lấy lại dữ liệu thừa, không sai số liệu).

## Kiểm thử

Unit test cho cleaning, factors, scoring (gồm đối chiếu tính tay `tests/test_handcalc.py`), collector, dịch vụ dashboard và kiểm tra ngoài mẫu. Kết quả đối chiếu iBoard và thử lỗi mạng/khóa sai ghi tại `TEST_LOG.md`.