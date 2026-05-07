# Skill Log — Quant Platform (Continuity Context)

Phiên cập nhật: 2026-05-07  
Mục tiêu: Bảo toàn ngữ cảnh để resume công việc ngay khi upload lại file này.

---

## 1) Mục tiêu tổng thể dự án

Refactor các tool quant rời rạc (thường dạng 1 file Streamlit lớn) thành nền tảng chuẩn hóa theo skeleton:

- Tách rõ `quant` / `ui` / `page`
- UI không chứa business logic nặng
- Quant layer không phụ thuộc Streamlit
- Data pipeline theo mô hình `data_lake` (app đọc file; updater script gọi API)
- Cho phép mở rộng nhiều tool và tạo report tổng hợp tự động

---

## 2) Root project và cấu trúc chuẩn

Root chính: `/Users/macos/Desktop/quant_platform`

Cấu trúc chuẩn:

- `app.py`: Trang chủ + nút Report Generation
- `config.py`: biến cấu hình toàn cục
- `data_lake/`: hồ dữ liệu CSV dùng chung
- `shared/data_loader.py`: loader chuẩn (đọc từ data_lake)
- `pages/*.py`: streamlit multipage entry (mỏng)
- `tools/<tool_name>/`
  - `quant/`: mô hình/tính toán
  - `ui/`: component hiển thị
  - `page.py`: bridge giữa UI và quant
  - `report.py`: snapshot hook cho report tổng hợp

---

## 3) Các tool đã chuẩn hóa

### 3.1 Fear & Greed
- Đã tồn tại từ đầu, giữ nguyên chuẩn.
- Đầu vào chính: `data_lake/market_data.csv`

### 3.2 Upside Ratio
- Port từ: `Desktop/upside ratio/upside_ratio.py`
- Đã chuẩn hóa vào: `tools/upside_ratio/`
- Bỏ hoàn toàn Gemini/AI block
- Dùng:
  - `market_data.csv` cho breadth returns
  - `vnindex_cache.csv` (nếu có) cho line VN-Index

### 3.3 Risk-Adjusted Growth
- Port từ: `Desktop/9999/risk adjusted growth rate/runcode.py`
- Đã chuẩn hóa vào: `tools/risk_adjusted_growth/`
- Đầu vào:
  - `market_data.csv` (giá latest)
  - `bank_fundamentals.csv`
  - `dividend_cache.csv` (static fallback)
- Đã vá lỗi quan trọng:
  - Nếu `ticker` bị đọc thành index do `load_custom(index_col=0)`, tự normalize lại để tránh lỗi “thiếu cột ticker”.

### 3.4 Market Breadth
- Port từ: `Desktop/9999/market_breadth/market_breadth.PY`
- Đã chuẩn hóa vào: `tools/market_breadth/`
- Tính `>MA20, >MA60, >MA125, >MA252`
- Top 10 volume:
  - dùng `data_lake/market_breadth_cache.csv` nếu có
  - thiếu volume cache thì hiển thị caption fallback, không crash

### 3.5 ESR Monitor
- Port vào: `tools/esr_monitor/`
- Bản hiện tại là proxy ESR theo pipeline data_lake, không dùng Telegram bot
- Inputs:
  - `market_data.csv`
  - `vnindex_cache.csv`

---

## 4) Pages đã đăng ký

- `pages/1_Fear_Greed.py`
- `pages/2_Upside_Ratio.py`
- `pages/3_Risk_Adjusted_Growth.py`
- `pages/4_Market_Breadth.py`
- `pages/5_ESR_Monitor.py`

Lưu ý: report screenshot tự quét `pages/*.py`, nên thêm page mới là report tự bao gồm page đó.

---

## 5) Data pipeline hiện tại

## 5.1 Giá thị trường chính
- File: `data_lake/market_data.csv`
- Script cập nhật: `update_data.py`
- `VNINDEX` đã thêm vào `tickers.csv`, nhưng lưu riêng file index.

## 5.2 VNINDEX riêng
- File: `data_lake/vnindex_cache.csv`
- Script: `update_data.py` có hàm `update_vnindex(start, end)`
- Trong `update()` sẽ gọi cập nhật VNINDEX trước.

## 5.3 Fundamentals ngân hàng
- File: `data_lake/bank_fundamentals.csv`
- Script: `update_bank_fundamentals.py`
- Trạng thái thực tế: API KBS có lúc lỗi `ConnectionError/RetryError`; khi fail thì giữ file cache cũ.

## 5.4 Dividend
- File: `data_lake/dividend_cache.csv`
- Hiện tại dùng static CSV do API dividend chưa ổn định/không khả dụng trên môi trường hiện tại.

---

## 6) Report generation (đã đổi sang screenshot PDF)

## 6.1 Nút trên app
- `app.py` có nút: `Report Generation`
- Nút gọi `generate_visual_report.py`

## 6.2 Cơ chế report
- Script: `generate_visual_report.py`
- Chức năng:
  - mở lần lượt Home + từng page
  - chụp full-page screenshot
  - ghép toàn bộ thành 1 PDF
- Tên file output: `ddmmyy_quant_report.pdf`
- Nơi lưu: Desktop user (ví dụ `/Users/macos/Desktop/070526_quant_report.pdf`)

---

## 7) Report snapshot dữ liệu dạng CSV (hook engine)

Ngoài report ảnh PDF, vẫn có engine snapshot dạng số:

- Script: `generate_report.py`
- Discovery động qua `tools/*/report.py`
- Mỗi tool có `snapshot(df_close, load_custom)` trả về dict
- Output CSV: `ddmmyy_quant_report.csv`

Dùng khi cần machine-readable report.

---

## 8) Quy ước khi thêm tool mới

Checklist chuẩn hóa:

1. Tạo `tools/<tool_name>/quant`, `tools/<tool_name>/ui`, `tools/<tool_name>/page.py`
2. Tạo entry `pages/<n>_<Tool_Name>.py`
3. Dữ liệu:
   - nếu dùng giá: đọc `load_close_prices()`
   - nếu dùng file khác: lưu vào `data_lake/*.csv` và đọc qua `load_custom(...)`
4. Nếu muốn report CSV auto include:
   - thêm `tools/<tool_name>/report.py` với hàm `snapshot(...)`
5. Nếu muốn report PDF screenshot include:
   - chỉ cần có page trong `pages/` (auto quét)

---

## 9) Vấn đề đã gặp và cách xử lý

1. `bank_fundamentals.csv thiếu cột ticker`
- Nguyên nhân: đọc CSV với `index_col=0`
- Cách xử lý: normalize lại index -> cột `ticker` trong tool RAG

2. API vnstock fundamentals không ổn định
- Lỗi: `ConnectionError/RetryError`
- Cách xử lý: fallback dùng cache cũ, không chặn app

3. Dividend API chưa xác nhận chạy ổn
- Quyết định hiện tại: giữ static `dividend_cache.csv`

---

## 10) Lệnh vận hành nhanh

- Chạy app:
  - `streamlit run /Users/macos/Desktop/quant_platform/app.py`

- Update giá + VNINDEX:
  - `python3 /Users/macos/Desktop/quant_platform/commnand/update_data.py`

- Update fundamentals bank:
  - `python3 /Users/macos/Desktop/quant_platform/commnand/update_bank_fundamentals.py`

- Tạo report PDF screenshot (ngoài UI):
  - đảm bảo app đang chạy ở `http://localhost:8501`
  - `python3 /Users/macos/Desktop/quant_platform/commnand/generate_visual_report.py`

- Tạo report CSV snapshot:
  - `python3 /Users/macos/Desktop/quant_platform/commnand/generate_report.py`

---

## 11) Universe chuẩn toàn platform

- `tickers.csv` là **single source of truth** cho universe toàn hệ thống.
- Mọi updater/tool phải ưu tiên đọc universe từ `tickers.csv`.
- Không hardcode danh sách mã riêng theo từng tool (trừ khi có yêu cầu đặc biệt).
- Nếu cần subset cho 1 tool, phải lọc từ universe chung thay vì tạo universe độc lập.

## 11) Nguyên tắc làm việc tiếp theo

- Ưu tiên giữ architecture ổn định theo skeleton hiện tại
- Không hardcode API key trong source
- Tool nào API không ổn định thì dùng data_lake cache + fallback rõ ràng
- Không để 1 tool làm crash toàn app/report; luôn fail-soft và ghi status/error



## 12) Cơ chế cache theo ngày (toàn bộ pages)

Đã áp dụng cơ chế cache theo ngày để giảm thời gian chờ khi mở lại tool trong cùng ngày.

- Helper dùng chung: `shared/daily_cache.py`
- Nguyên tắc:
  - Tính xong -> lưu cache với `cache_date = ngày hiện tại`
  - Mở lại cùng ngày -> đọc cache, hiển thị ngay
  - Sang ngày mới -> tự động tính lại và ghi cache mới

Các page đã áp dụng:
- Fear Greed
- Upside Ratio
- Risk Adjusted Growth
- Market Breadth
- ESR Monitor
- Dispersion (đã có cache theo ngày riêng trong `data_lake` + kiểm tra `cache_date`)

UI hiển thị trạng thái cache:
- `⚡ Dùng cache cùng ngày...`
- `💾 Đã tạo cache ngày mới...`

