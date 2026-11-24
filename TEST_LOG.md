# Nhật ký kiểm thử thủ công 

## A. Đối chiếu số liệu với nguồn công khai (SSI iBoard)

Ngày đối chiếu: 23/11/2026. Nguồn công khai: SSI iBoard.

| Mã | Chỉ tiêu | STOCKWISE | Nguồn công khai | Kết quả |
|:---|:---------|----------:|----------------:|:-------:|
| FPT | Giá đóng cửa (đồng) | 46.850 | 46.850 | ✅ Khớp |
| FPT | Khối lượng khớp (cổ phiếu) | 16.985.400 | 16.985.400 | ✅ Khớp |
| FPT | Giá trị khớp (tỷ đồng) | 778,26 | 778,26 | ✅ Khớp |
| FPT | Khối ngoại mua ròng (tỷ đồng) | +25,03 | +25,03 | ✅ Khớp |
| PDR | Giá đóng cửa (đồng) | 11.200 | 11.200 | ✅ Khớp |
| PDR | Khối lượng khớp (cổ phiếu) | 3.634.100 | 3.634.100 | ✅ Khớp |
| PDR | Giá trị khớp (tỷ đồng) | 40,27 | 40,27 | ✅ Khớp |
| PDR | Khối ngoại mua ròng (tỷ đồng) | −2,09 | −2,09 | ✅ Khớp |

> Mua ròng mang dấu **+**, bán ròng mang dấu **−**. Cả 8 chỉ tiêu đều chênh lệch bằng 0.

## B. Điều kiện lỗi
Mỗi dòng: thực hiện, kết quả mong đợi, kết quả thực tế, bằng chứng (ảnh/log).

| # | Tình huống | Cách tạo | Kết quả  | 
|---|------------|----------|----------|
| 1 | Mất mạng | Tắt Wi-Fi chạy `python -m src.data.collector --limit 5` | Mã ghi trạng thái `error`, báo rõ, không treo, không mất dữ liệu cũ |
| 2 | Token/khóa sai | Tạm đổi một ký tự trong khóa cấu hình, chạy collector | Dừng với "lỗi xác thực", không ghi dữ liệu sai | 
| 3 | API trả lỗi | Dùng mã không tồn tại, hoặc ngày kết thúc trong tương lai xa | Một mã lỗi không làm hỏng cả lượt | 
| 4 | Hết quota | Chạy `--force` toàn thị trường liên tục | Dừng/chờ, ghi note "dừng do quota", chạy lại thì tiếp tục | 
| 5 | CSDL rỗng | Mở dashboard với `data\stockwise.db` mới | Banner đỏ, hướng dẫn chạy collector, không lỗi đỏ Python | 
| 6 | Dữ liệu cũ | Đổi `STALE_DAYS` về 0 hoặc dùng DB cũ | Banner vàng "dữ liệu đã cũ" | 
| 7 | Tổng trọng số ≠ 100 | Thanh trượt tùy chỉnh, tổng 90 | Báo lỗi tổng trọng số, không crash | 
| 8 | Ngày đánh giá không đủ lịch sử | Chọn phiên đầu + cửa sổ 5 | Thông báo cần thêm dữ liệu | 

Ngày thực hiện: 23/11/2026

## C. Tính tay đối chiếu
Xem `tests/test_handcalc.py` (3 mã, cửa sổ 2 phiên).