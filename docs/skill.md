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
- Nơi lưu: Thư mục reports của dự án (ví dụ `reports/070526_quant_report.pdf`)

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
  - `python3 /Users/macos/Desktop/quant_platform/command/update_data.py`

- Update fundamentals bank:
  - `python3 /Users/macos/Desktop/quant_platform/command/update_bank_fundamentals.py`

- Tạo report PDF screenshot (ngoài UI):
  - đảm bảo app đang chạy ở `http://localhost:8501`
  - `python3 /Users/macos/Desktop/quant_platform/command/generate_visual_report.py`

- Tạo report CSV snapshot:
  - `python3 /Users/macos/Desktop/quant_platform/command/generate_report.py`

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


---

## 13) Phiên cập nhật 2026-05-09

### 13.1 AI CIO (`shared/ai_cio.py`) — Fix lỗi import + Mở rộng 7 tool

**Lỗi đã fix:**
1. `calculate_risk_score` trả về `pd.DataFrame` (không phải tuple) → sửa logic lấy `latest`, `prev`, `score` từ DataFrame
2. `run_upside_downside_simulation` không tồn tại → thay bằng `build_breadth_series` + `run_hybrid_ensemble_mc`
3. `load_bank_fundamentals` không tồn tại → thay bằng `load_custom("bank_fundamentals.csv")` + `build_base_table` để tính `P/B Gốc` và `Cash Payout Ratio`

**Mở rộng từ 5 → 7 báo cáo:**
- Thêm `run_market_breadth()`: chạy `compute_breadth()`, lấy số mã >MA20/60/125/252 + tỷ lệ %, top volume leaders, gọi Kimi API, cache
- Thêm `run_esr_monitor()`: chạy `calculate_esr()`, lấy SSI, status, top 3 PCA weights, gọi Kimi API, cache
- `run_executive_summary()` giờ gộp 7 báo cáo vào `all_reports`

### 13.2 Tích hợp AI analysis cho Market Breadth

File sửa:
- `tools/market_breadth/ui/sidebar.py`: thêm `Kimi API Key` input
- `tools/market_breadth/page.py`: thêm section AI analysis sau phần hiển thị metrics
  - Thu thập: ngày, tổng số mã, số mã >MA20/60/125/252 + tỷ lệ %, top 10 volume giữ MA20 và MA252
  - Đọc prompt `promt/Market Breadth promt.md`, replace placeholder bằng dữ liệu thực
  - Gọi Kimi API (`moonshot-v1-128k`), lưu cache `daily_cache/market_breadth_{date}.txt`
  - Nút "Chạy lại" để xóa cache

### 13.3 Tích hợp AI analysis cho ESR Monitor

File sửa:
- `tools/esr_monitor/page.py`: thêm `Kimi API Key` input vào sidebar + section AI analysis sau chart
  - Thu thập: ngày, điểm VN30, trạng thái so với MA, SSI (%), SAFE/WARNING/CRITICAL, top 3 PCA weights
  - Đọc prompt `promt/ESR monitor promt.md`, replace placeholder bằng dữ liệu thực
  - Gọi Kimi API (`moonshot-v1-128k`), lưu cache `daily_cache/esr_monitor_{date}.txt`
  - Nút "Chạy lại" để xóa cache

### 13.4 Cập nhật Executive Summary Prompt

- `promt/executive_summary_promt.md`: cập nhật từ 5 phòng ban → 7 phòng ban (thêm Market Breadth và ESR Monitor)

### 13.5 Đổi nguồn chính data update từ KBS → VCI

File sửa: `command/update_data.py`
- `fetch_close()`: default `source="VCI"` (trước là `"KBS"`)
- `update_vnindex()`: ưu tiên VCI, fallback KBS
- Loop stock tickers: gọi VCI trước, nếu `None` thì log và thử fallback KBS
- Bỏ hàm `fetch_f1_vci()` riêng lẻ (VN30F1M giờ dùng `fetch_close` chung với source VCI)

### 13.6 Cache reuse cross-tool

AI CIO tuân thủ nguyên tắc: trước khi gọi Kimi API, kiểm tra `daily_cache/{tool}_{date}.txt`. Nếu user đã chạy AI ở tool riêng lẻ trước đó → lấy cache dùng luôn, không tốn token gọi lại.

### 13.6 Bỏ Report Generation, thay bằng Xuất PDF AI CIO

File sửa: `app.py`
- Bỏ toàn bộ logic `subprocess` gọi `generate_visual_report.py` (Report Generation)
- Thay nút trái thành **"📄 Xuất PDF Report AI CIO"**
  - Dùng `fpdf2` tạo PDF với font Arial Unicode (hỗ trợ tiếng Việt)
  - Ưu tiên đọc từ `st.session_state["cio_report"]` → fallback file cache `executive_summary_{date}.txt`
  - Nếu chưa có báo cáo: báo lỗi "Chưa có báo cáo AI CIO. Vui lòng chạy Executive Summary trước."
  - Nếu đã có: tạo PDF lưu `reports/ddmmyy_executive_summary.pdf` + hiển thị nút download
- Thêm status AI CIO trên trang chủ (tương tự Data lake):
  - `✅ Report AI CIO đã sẵn sàng — dd/mm/YYYY HH:MM`
  - `ℹ️ Chưa có report AI CIO. Chạy '🔥 Executive Summary (AI CIO)' để tạo.`

### 13.7 Đổi COE mặc định từ 12% → 14%

File sửa:
- `tools/risk_adjusted_growth/ui/sidebar.py`: `value=12.0` → `value=14.0`
- `shared/ai_cio.py`: `coe_decimal=0.12` → `0.14`, prompt replace `"12.0"` → `"14.0"`
- `tools/risk_adjusted_growth/report.py`: `coe_decimal=0.12` → `0.14`

---

## 15) Phiên cập nhật 2026-05-09 (tiếp) — Model AI Configurable + Cross-platform fix

### 15.1 Chuyển model AI sang `moonshot-v1-128k` + Configurable qua `config.py`

**Vấn đề:** User muốn dùng `moonshot-v1-128k` thay vì `kimi-k2.6`, và có thể tự thay đổi model/temperature từ 1 chỗ.

**Thay đổi:**
- `config.py`: thêm 2 biến cấu hình:
  ```python
  AI_MODEL       = os.getenv("AI_MODEL", "kimi-k2.6")
  AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "1.0"))
  ```
  - Mặc định: `kimi-k2.6`, temperature `1.0`
  - Có thể override qua biến môi trường hoặc sửa trực tiếp `config.py`
- `shared/ai_cio.py`: hàm `call_kimi()` đọc `AI_MODEL`, `AI_TEMPERATURE` từ config
- Các file page (7 tool): đều import `AI_MODEL`, `AI_TEMPERATURE` từ config, truyền vào `client.chat.completions.create(...)`
- Cập nhật button labels: `(Kimi AI k1.5/k2.6)` → `(Moonshot AI v1 128k)` (tạm thờ)

### 15.2 Fix hardcode Windows path cho prompt files

**Vấn đề:** File Python hardcode đường dẫn Windows tuyệt đối:
```python
r"c:\Users\ADMIN\Desktop\quant_platform\promt\fear greed promt.md"
```
→ Lỗi `No such file or directory` khi chạy trên macOS.

**Thay đổi:**
- Tất cả đường dẫn prompt chuyển sang dùng `ROOT_DIR` từ `config.py`:
  ```python
  str(ROOT_DIR / "promt" / "fear greed promt.md")
  ```
- Các file đã sửa:
  - `shared/ai_cio.py` — 8 prompt paths
  - `tools/dispersion/page.py`, `esr_monitor/page.py`, `fear_greed/page.py`, `manipulation/page.py`, `market_breadth/page.py`, `risk_adjusted_growth/page.py`, `upside_ratio/page.py`

### 15.3 Fix lỗi tạo PDF trên macOS (font + library)

**Vấn đề 1:** `fpdf` 1.7.2 không hỗ trợ TTF Unicode → lỗi `can only concatenate str (not "int") to str`
**Vấn đề 2:** Font DejaVu tải về bị corrupt (file ~300KB, thiếu data)

**Thay đổi:**
1. Gỡ `fpdf`, cài `fpdf2>=2.7.0` (hỗ trợ Unicode TTF đúng chuẩn)
2. Tải lại font **DejaVuSans.ttf** và **DejaVuSans-Bold.ttf** đúng bản release 2.37 (từ GitHub official) vào `fonts/`
3. Sửa `app.py`:
   - `text_width = int(pdf.w - 20)` (fpdf 1.7 cần int, fpdf2 chấp nhận float nhưng vẫn giữ int cho an toàn)
   - Dùng `ln=1` thay vì `ln=True`
   - Đổi toàn bộ font name từ `ArialUnicode` → `DejaVu`
4. Cập nhật `requirements.txt`: thêm `fpdf2>=2.7.0`

**Kết quả:** Xuất PDF AI CIO trên macBook hoạt động bình thường, tiếng Việt có dấu hiển thị đúng.

---

---

## 17) Phiên cập nhật 2026-05-10 — Multi-Provider AI + Auto Workflow + GitHub Sync

### 17.1 Thêm DeepSeek V4 Pro vào toàn bộ AI analysis

**File sửa:**
- `config.py`: thêm `AI_PROVIDER_MAP` định nghĩa 2 provider: `kimi-2.6` và `deepseek-v4-pro`
- `shared/ai_cio.py`: refactor `call_kimi()` → `call_ai()`; cache tách biệt theo provider (`{tool}_{provider}_{date}.txt`); `run_executive_summary()` nhận `provider_key`
- 7 tool `page.py` + 6 `sidebar.py` + `app.py`: thêm dropdown chọn model AI, textbox API Key chung (không còn ghi cứng "Kimi"), button AI tự động hiển thị tên model

**Kết quả:** User có thể chọn Kimi hoặc DeepSeek ở bất kỳ tool nào. Cache độc lập theo model, không ghi đè.

### 17.2 Fix AI CIO status + PDF selector đa model

**File sửa:** `app.py`
- Status trên trang chủ: **quét tất cả provider** để hiển thị, thay vì chỉ kiểm tra provider mặc định
- Xuất PDF: nếu có **nhiều bản** báo cáo (Kimi + DeepSeek) → hiện dropdown chọn model trước khi tạo PDF
- Tên file PDF có prefix model: `ddmmyy_kimi_2_6_executive_summary.pdf` / `ddmmyy_deepseek_v4_pro_executive_summary.pdf`

### 17.3 Prompt AI CIO thêm dòng cuối bắt buộc

**File sửa:** `promt/executive_summary_promt.md`
- Thêm yêu cầu AI viết dòng cuối cùng chính xác theo format:
  ```
  final score & regime : <score> ; regime : <regime>
  ```
- Phục vụ cho việc parse tự động trong workflow

### 17.4 Workflow GitHub Actions tự động chạy AI CIO

**File mới:**
- `.github/workflows/ai_cio_daily.yml` — Cron `0 20 * * 0-4` (3h sáng VN, T2–T6)
- `command/run_ai_cio_auto.py` — Script auto-run AI CIO bằng DeepSeek

**Logic (đã cập nhật):**
1. Kiểm tra cache ngày hiện tại
   - **CÓ cache** → đọc cache, tạo PDF, gửi Telegram (KHÔNG gọi API)
   - **KHÔNG cache** → gọi API DeepSeek → lưu cache → tạo PDF → gửi Telegram
2. Tạo PDF từ báo cáo
3. Parse dòng cuối `final score & regime`
4. Gửi Telegram (tin nhắn + file PDF)
5. Auto-commit cache + PDF về GitHub repo

**Flags:**
- `--force` / `-f`: xóa cache cũ, gọi API mới

**Secrets cần thiết lập trên GitHub:**
- `DEEPSEEK_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### 17.5 GitHub Sync từ Streamlit Cloud

**File mới:** `shared/github_sync.py` — Upload file lên GitHub qua REST API

**File sửa:** `app.py`
- Sau khi chạy AI CIO (manual), tự động upload cache lên GitHub repo
- Lấy `GITHUB_TOKEN` từ `st.secrets` hoặc env
- Giúp file báo cáo xuất hiện trên GitHub ngay cả khi chạy từ Streamlit Cloud container

### 17.6 Thêm nút "Tạo lại (ghi đè cache)" cho AI CIO

**File sửa:** `app.py`
- Khi đã có cache, UI hiện 2 nút: `🚀 Bắt đầu Tổng hợp` (đọc cache) và `🔄 Tạo lại (ghi đè cache)` (xóa cache cũ → gọi API mới)

### 17.7 Fix GitHub Actions workflow permissions

**File sửa:** `.github/workflows/ai_cio_daily.yml`
- Lỗi `403 Permission denied` khi `git push` từ GitHub Actions → cần bật **Workflow permissions: Read and write** trong repo Settings → Actions → General
- Không dùng `token: ${{ secrets.PAT_TOKEN }}` nếu chưa thiết lập PAT; dùng default `GITHUB_TOKEN` với đúng quyền

### 17.8 Fix GitHub Sync robustness

**File sửa:** `shared/github_sync.py`
- Đọc token động mỗi lần gọi (`_get_token()`), hỗ trợ cả `st.secrets["GITHUB_TOKEN"]` và `st.secrets.get()`
- Chuyển auth sang `Bearer` thay vì `token` để tương thích cả Classic PAT và Fine-grained PAT
- Thêm `test_connection()` kiểm tra auth + quyền repo trước khi upload
- Thêm `X-GitHub-Api-Version` header
- Trả về `file_url` sau upload để UI hiển thị link trực tiếp

**File sửa:** `app.py`
- Thêm collapsible **"🔧 Kiểm tra GitHub Sync"** trên trang chủ để debug connection
- Đổi `st.info` → `st.warning` khi sync lỗi để user dễ thấy

---

## 18) Nguyên tắc làm việc tiếp theo (cập nhật)

- AI CIO hiện tại tổng hợp **7 phòng ban** (Fear Greed, Manipulation, Dispersion, Upside Ratio, Risk Adjusted Growth, Market Breadth, ESR Monitor)
- Tất cả tool đều có AI analysis riêng lẻ + cache cross-tool
- **Model AI & temperature configurable từ 1 chỗ** (`config.py`): đổi `AI_MODEL` / `AI_TEMPERATURE` là toàn bộ platform cùng đổi theo
- **Multi-provider AI**: Kimi 2.6 + DeepSeek V4 Pro; cache tách biệt; UI chọn model ở tất cả tool
- **Auto-report**: Workflow cron 3h sáng T2–T6 chạy DeepSeek
  - Có cache → đọc cache → tạo PDF → gửi Telegram
  - Không cache → gọi API → lưu cache → tạo PDF → gửi Telegram
  - Auto-commit cache + PDF về GitHub repo
- **Manual-sync**: Streamlit Cloud tự động upload cache lên GitHub sau khi chạy AI CIO (cần `GITHUB_TOKEN` trong Secrets)
- **Force refresh**: Cho phép user ghi đè cache cùng ngày nếu muốn tái tạo báo cáo
- **GitHub Actions permissions**: Đảm bảo bật `Read and write permissions` cho workflow
- Nguồn data chính: **VCI**, fallback **KBS**
- Report duy nhất trên app: **PDF Export của AI CIO** (thay thế screenshot PDF)
- COE mặc định: **14%**
- **Không hardcode đường dẫn tuyệt đối theo OS** (Windows/macOS); luôn dùng `ROOT_DIR` hoặc `Path(__file__)`
- **Font PDF:** dùng `fpdf2` + font `DejaVuSans` trong `fonts/` (không dựa vào system font)
