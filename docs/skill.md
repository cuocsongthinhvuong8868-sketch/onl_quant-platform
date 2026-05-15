# Skill Log — Quant Platform (Continuity Context)

Phiên cập nhật: 2026-05-14
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

Root chính: `C:\Users\ADMIN\Documents\GitHub\onl_quant-platform`

Cấu trúc chuẩn:

- `app.py`: Trang chủ — 3 nhánh điều hướng (Macro, Micro, Behavioral Finance) + AI CIO Executive Summary + PDF export
- `config.py`: biến cấu hình toàn cục
- `data_lake/`: hồ dữ liệu CSV dùng chung
- `shared/data_loader.py`: loader chuẩn (đọc từ data_lake)
- `pages/`
  - `A_Macro_Analysis.py`: Nhánh Vĩ mô — grid menu + gọi render() động (1 tool: Fed Liquidity)
  - `B_Micro_Analysis.py`: Nhánh Vi mô (🚧 đang phát triển)
  - `C_Behavioral_Finance.py`: Nhánh Tài chính Hành vi — **gộp 9 tool hiện tại** dạng grid menu + gọi render() động
  - `tools_page_A/`: thư mục chứa entry tool nhánh A (ẩn khỏi sidebar)
    - `_1_Fed_Liquidity.py`
  - `tools_page_C/`: thư mục chứa 9 entry tool (ẩn khỏi sidebar)
    - `_1_Fear_Greed.py` … `_9_Var_CVaR_VNINDEX.py`
- `tools/<tool_name>/`
  - `quant/`: mô hình/tính toán
  - `ui/`: component hiển thị
  - `page.py`: bridge giữa UI và quant (hàm `render()` hoặc `show()`)
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
- **Đã nâng cấp hoàn chỉnh (2026-05-11):** từ proxy 3-pillar → **full 5-pillar SSI** port từ `Desktop/9999/ESR monitor/ESR.app.py`
- **5 Pillar gốc:**
  - `S_VOL`: Realized volatility annualized (20d)
  - `S_PRES`: Selling pressure — down-day volume share (5d)
  - `S_COR`: Systemic correlation — PCA-1 explained variance (60d)
  - `S_LIQ`: Illiquidity — cross-sectional median Amihud (20d)
  - `S_VAL`: Valuation tension — 252d return - deposit rate
- **Downside variants:** `S_VOL_DOWN` (semi-deviation), `S_COR_DOWN` (down-days only), `S_LIQ_DOWN` (down-day Amihud)
- **Aggregation:** Expanding-window PCA(1) on rank-transformed pillars, look-ahead-free, sign-aligned with anchor pillar `S_VOL`
- **Output:** SSI ∈ [0, 1] + EMA smoothing
- **HMM Regime Classifier:** 2-state Gaussian HMM on SSI → binary HIGH_STRESS regime + decision boundary threshold
- **4-State Market Classification:** Kết hợp HMM regime + trend MA200 → `EUPHORIC_RISK`, `ACTIVE_STRESS`, `HEALTHY`, `CALM_CORRECTION`
- **File cấu trúc mới:**
  - `quant/metrics.py`: `PillarEngine`, `SSIResult`, `SSIAggregator`, `HMMRegimeClassifier`, `classify_market_state()`, `run_esr_pipeline()`
  - `ui/charts.py`: `render_esr_chart()` (2 panel + 4-state shading + HMM threshold) + `render_pillar_diagnostics()` (3 tabs)
  - `page.py`: Full UI mới với PCA warmup, EMA span, pillar mode toggle, trend MA, HMM toggle, market regime card, PCA weights bar chart
  - `report.py`: snapshot dùng pipeline mới, thêm `pca_concentration`, `pca_weights`, `n_tickers`
- **Inputs:**
  - `market_data.csv`
  - `vnindex_cache.csv`
- **Volume proxy:** Dùng flat 1e9 (do data_lake không có real volume)
- **Lưu ý:** Đã xóa hàm `calculate_esr()` cũ, thay bằng `run_esr_pipeline()`

### 3.6 Dispersion
- Port vào: `tools/dispersion/`
- Tính phân tán (volatility skew, term structure) của thị trường

### 3.7 Manipulation
- Port vào: `tools/manipulation/`
- Phát hiện dấu hiệu thao túng giá qua các metrics đặc biệt

### 3.8 VaRES Engine
- Port từ: `Desktop/VaR-ES Engine.py`
- Chuẩn hóa vào: `tools/va_res/`
- 3 module: A (Single Ticker), B (VN30 Stress), C (Market Complacency)
- AI analysis chỉ ở Module C (kèm data Module B inline)
- Self-Baseline Complacency: rolling quantile 0.1 của chính Spread từng cổ phiếu (không dùng benchmark VNINDEX)
- Inputs:
  - `market_data.csv` (giá tất cả mã cho Module A/C)
  - `vnindex_cache.csv` (VNINDEX real cho Module C, thay thế synthetic mean)

### 3.9 Var-CVaR(ES) VNINDEX
- Tạo mới hoàn toàn
- Chuẩn hóa vào: `tools/var_cvar_vnindex/`
- Chỉ focus VNINDEX
- Tính: rolling σ30, Parametric VaR 95%, Historical VaR 95% (3 năm), ES 95%
- Input: `vnindex_cache.csv`

### 3.10 Fed Liquidity Monitor (Nhánh A — Macro)
- Port từ: `Desktop/9999/fed/` (fed.py + feddashborad.py)
- Chuẩn hóa vào: `tools/fed_liquidity/`
- **Logic core:**
  - Pull 3 series FRED: `WALCL` (Fed Balance Sheet), `WTREGEN` (Treasury General Account), `RRPONTSYD` (Overnight Reverse Repo)
  - Chuẩn hoá: `RRPONTSYD × 1000` (đổi đơn vị → triệu USD)
  - Resample `W-WED` (weekly Wednesday), ffill, dropna
  - `Net_Liquidity = WALCL − WTREGEN − RRPONTSYD`
  - `Impulse = Net_Liquidity.diff()` (delta tuần)
  - `Impulse_EMA = Impulse.ewm(span=4)`
  - `Z_Score = (Impulse − mean_52W) / std_52W`
  - Signal:
    - **ADD**: `Impulse_EMA > 0 AND Z_Score >= +1`
    - **CUT**: `Impulse_EMA < 0 AND Z_Score <= -1`
    - **HOLD**: else
  - Filter từ `START_DATE = 2017-01-01`
- **File cấu trúc:**
  - `quant/metrics.py`: `fetch_fed_data()`, `process_liquidity_logic()`, `summarize_latest()`
  - `ui/sidebar.py`: date picker + clear cache button
  - `ui/charts.py`: `plot_net_liquidity()` (line + colored dots theo Signal), `plot_momentum()` (bar Impulse + line EMA), `plot_zscore()` (Z-Score với vùng ADD/CUT shading)
  - `page.py`: `render()` — header metrics (4+3 cards), 2 charts chính + expander Z-Score + bảng dữ liệu, AI block 2 tabs (current/history)
  - `report.py`: `snapshot()` đọc cache CSV cho discovery engine
- **Inputs:** `data_lake/fed_liquidity_cache.csv` (do updater tạo)
- **Updater:** `command/update_fed_liquidity.py` — gọi FRED API → process → save CSV
  - Đọc `FRED_API_KEY` từ env / .env / config
  - CLI: `python command/update_fed_liquidity.py [--api-key xxx] [--from-date YYYY-MM-DD]`
- **Prompt AI:** `promt/fed_liquidity_promt.md`
- **Entry:** `pages/tools_page_A/_1_Fed_Liquidity.py` (gọi `tools.fed_liquidity.page.render()`)
- **Lưu ý:**
  - Tool dùng pattern app **đọc file** (data_lake) — KHÔNG gọi FRED API trực tiếp trong app
  - Đã thêm `fredapi>=0.5.2` vào `requirements.txt`
  - Chưa tích hợp vào AI CIO Executive Summary (data weekly, frequency khác 9 tool kia)

---

## 4) Pages & Cấu trúc 3 nhánh

### 4.1 Sơ đồ 3 nhánh

```
app.py (Trang chủ)
  ├── 📈 A_Macro_Analysis.py         — Nhánh Vĩ mô
  │     └── 🏦 Fed Liquidity Monitor
  ├── 🔬 B_Micro_Analysis.py         — Nhánh Vi mô (🚧 đang phát triển)
  └── 🧠 C_Behavioral_Finance.py     — Nhánh Tài chính Hành vi
        ├── 🎯 Fear & Greed
        ├── 🧬 Upside/Downside Ratio
        ├── 📊 Risk-Adjusted Growth
        ├── 📈 Market Breadth
        ├── ⚡ ESR Monitor
        ├── 🔄 Dispersion
        ├── 🛡️ VaRES Engine
        ├── 🔍 Manipulation Detection
        └── 📉 Var-CVaR VNINDEX
```

### 4.2 Pages đăng ký trên sidebar (Streamlit multi-page)

**Pages hiển thị trên sidebar (3 page chính):**
- `pages/A_Macro_Analysis.py`
- `pages/B_Micro_Analysis.py`
- `pages/C_Behavioral_Finance.py`

**Pages ẩn (trong `pages/tools_page_C/` — Streamlit bỏ qua vì nằm trong thư mục con + tiền tố `_`):**
- `pages/tools_page_C/_1_Fear_Greed.py` → gọi `tools.fear_greed.page.render()`
- `pages/tools_page_C/_2_Upside_Ratio.py` → gọi `tools.upside_ratio.page.render()`
- `pages/tools_page_C/_3_Risk_Adjusted_Growth.py` → gọi `tools.risk_adjusted_growth.page.render()`
- `pages/tools_page_C/_4_Market_Breadth.py` → gọi `tools.market_breadth.page.render()`
- `pages/tools_page_C/_5_ESR_Monitor.py` → gọi `tools.esr_monitor.page.render()`
- `pages/tools_page_C/_6_Dispersion.py` → gọi `tools.dispersion.page.render()`
- `pages/tools_page_C/_7_VaRES_Engine.py` → gọi `tools.va_res.page.show()`
- `pages/tools_page_C/_8_Manipulation.py` → gọi `tools.manipulation.page.render()`
- `pages/tools_page_C/_9_Var_CVaR_VNINDEX.py` → gọi `tools.var_cvar_vnindex.page.show()`

Lưu ý:
- VaRES Engine và Var-CVaR VNINDEX dùng `show()` thay vì `render()` vì lịch sử code cũ.
- Behavioral Finance page dùng `__import__()` động + `getattr()` để gọi đúng hàm theo từng tool.
- Các tool vẫn có thể truy cập riêng lẻ qua URL trực tiếp (vd: `/_1_Fear_Greed`), nhưng không hiển thị trên sidebar.

---

## 5) Data pipeline hiện tại

## 5.1 Giá thị trường chính (Smart Incremental)
- File: `data_lake/market_data.csv`
- Script cập nhật: `command/update_data.py`
- **Incremental mode (default):** Nếu file đã tồn tại → chỉ tải ngày mới từ `last_date - 3 ngày` đến `today`, merge bằng `combine_first()` (union indices, giữ old data nếu new là NaN).
  - **Lưu ý quan trọng:** Không dùng `.loc[df_new.index, col] = df_new[col]` vì silently drop các ngày chưa có trong old DataFrame.
- **Backfill mode:**
  - `python command/update_data.py --backfill 2190` (~6 năm)
  - `python command/update_data.py --from-date 2020-01-01`
- `VNINDEX` đã thêm vào `tickers.csv`, nhưng lưu riêng file index.

## 5.2 VNINDEX riêng
- File: `data_lake/vnindex_cache.csv`
- Script: `update_data.py` có hàm `update_vnindex(start, end)`
- Trong `update()` sẽ gọi cập nhật VNINDEX trước, cùng logic incremental/backfill.

## 5.3 Fundamentals ngân hàng
- File: `data_lake/bank_fundamentals.csv`
- Script: `update_bank_fundamentals.py`
- Trạng thái thực tế: API KBS có lúc lỗi `ConnectionError/RetryError`; khi fail thì giữ file cache cũ.

## 5.4 Dividend
- File: `data_lake/dividend_cache.csv`
- Hiện tại dùng static CSV do API dividend chưa ổn định/không khả dụng trên môi trường hiện tại.

## 5.5 Fed Liquidity (FRED)
- File: `data_lake/fed_liquidity_cache.csv`
- Script: `command/update_fed_liquidity.py`
- Pull từ FRED API 3 series: `WALCL`, `WTREGEN`, `RRPONTSYD` → process toàn bộ pipeline → lưu CSV đã processed
- Cấu hình API: `FRED_API_KEY` trong `.env` (hoặc env var, hoặc `--api-key` CLI)
- Tần suất khuyến nghị: weekly (Fed release WALCL vào thứ 5)
- Output columns: `DATE, WALCL, WTREGEN, RRPONTSYD, Net_Liquidity, Impulse, Impulse_EMA, Z_Score, Signal`

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
  - `streamlit run C:\Users\ADMIN\Documents\GitHub\onl_quant-platform\app.py`

- Update giá + VNINDEX (incremental — chỉ tải ngày mới):
  - `python C:\Users\ADMIN\Documents\GitHub\onl_quant-platform\command\update_data.py`
- Backfill lịch sử dài (~6 năm):
  - `python C:\Users\ADMIN\Documents\GitHub\onl_quant-platform\command\update_data.py --backfill 2190`
- Backfill từ ngày cụ thể:
  - `python C:\Users\ADMIN\Documents\GitHub\onl_quant-platform\command\update_data.py --from-date 2020-01-01`

- Update fundamentals bank:
  - `python C:\Users\ADMIN\Documents\GitHub\onl_quant-platform\command\update_bank_fundamentals.py`

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
- Dispersion
- VaRES Engine
- Manipulation
- Var-CVaR VNINDEX

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

### 13.3 Tích hợp AI analysis cho ESR Monitor (gốc)

**File sửa (phiên bản gốc, trước refactor):**
- `tools/esr_monitor/page.py`: thêm `Kimi API Key` input vào sidebar + section AI analysis sau chart
  - Thu thập: ngày, điểm VN30, trạng thái so với MA, SSI (%), SAFE/WARNING/CRITICAL, top 3 PCA weights
  - Đọc prompt `promt/ESR monitor promt.md`, replace placeholder bằng dữ liệu thực
  - Gọi Kimi API (`moonshot-v1-128k`), lưu cache `daily_cache/esr_monitor_{date}.txt`
  - Nút "Chạy lại" để xóa cache

**Nâng cấp (2026-05-11):** page.py được refactor hoàn toàn:
- Sidebar mới: PCA warmup, EMA span, deposit rate, pillar mode (downside/classic), trend MA window, HMM toggle
- Header: Market Regime card với 4-state color coding + emoji, PCA Concentration metric, state distribution, PCA weights bar chart
- Chart: SSI 2-panel với HMM threshold line, 4-state shading, trend MA
- Pillar diagnostics expander: 3 tabs (Raw Pillars, Expanding Ranks, Weight Evolution)
- AI analysis: dữ liệu mới (SSI từ `result.ssi`, EVR, market state, threshold, pillar mode)

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

## 19) Phiên cập nhật 2026-05-10 (tiếp) — VaRES Engine + Var-CVaR VNINDEX + Pipeline Refactor

### 19.1 Tích hợp VaRES Engine (Tool #8)

**File gốc:** `Desktop/VaR-ES Engine.py` (297 dòng, Polars/Numba backend)

**Chuẩn hóa vào:** `tools/va_res/`
- `quant/metrics.py`: `SystemicRiskEngine` với `RiskConfig`, `numba_historical_risk()`, `calculate_risk_metrics()` (Cornish-Fisher + Historical), `calculate_contagion_index()`, `calculate_complacency_index()`, `get_latest_risk_status()`
- `ui/sidebar.py`: Menu radio (A/B/C) + date picker
- `ui/charts.py`: 3 plotly charts (individual risk, systemic risk, complacency index)
- `page.py`: 3 module (A: single ticker, B: VN30 stress, C: market complacency) + AI analysis block
- `report.py`: `snapshot()` cho AI CIO — tính Stress Index + Complacency Index + top 3 crash/mispriced

**Pages:** `pages/7_VaRES_Engine.py`

**Prompt:** `promt/va_res_promt.md`

**Tích hợp AI CIO:**
- `shared/ai_cio.py`: thêm `run_va_res()` → gọi `vares_snapshot()`, gọi AI, cache
- `run_executive_summary()`: gộp 8 báo cáo
- `promt/executive_summary_promt.md`: thêm section 8 (toán học VaRES)
- `app.py`: spinner "8 báo cáo"

### 19.2 Fix lỗi Polars ColumnNotFoundError trong VaRES

**Nguyên nhân:** `.with_columns([...])` chuỗi trong `calculate_risk_metrics` — cột `mean`/`std` vừa tạo không thể tham chiếu ngay trong cùng block khi tính `kurtosis`.

**Fix:** Tách thành 2 `.with_columns()` riêng biệt (chain).
- File sửa: `tools/va_res/quant/metrics.py` + `Desktop/VaR-ES Engine.py`

### 19.3 Cập nhật calculate_complacency_index — Self-Baseline

**Thay đổi cốt lõi:**
- Bỏ `bench_spread` từ benchmark VNINDEX
- Thay bằng `self_baseline_spread` = rolling quantile 0.1 của chính Spread của cổ phiếu đó (252 phiên)
- `dynamic_threshold = self_baseline_spread × multiplier`

**File tham khảo:** `Desktop/calculate_complacency_index.txt`

**File sửa:** `tools/va_res/quant/metrics.py`

### 19.4 Restructure AI VaRES — Chỉ Module C, kèm data Module B

**Thay đổi:**
- Module A/B không còn AI analysis riêng
- Module C (Complacency) khi bấm AI → tính Module B (VN30 Stress) inline → gộp cả B + C vào prompt
- Prompt `promt/va_res_promt.md` cập nhật: 2 section MODULE B và MODULE C + placeholder [Breached Count], [Mispriced Count]

**File sửa:** `tools/va_res/page.py`, `tools/va_res/report.py`, `shared/ai_cio.py`, `promt/va_res_promt.md`

### 19.5 VNINDEX data source cho Module C

**Thay đổi:** Thay vì tính Synthetic Index = mean(tickers), giờ load VNINDEX từ `data_lake/vnindex_cache.csv` qua `load_custom()`.

**File sửa:** `tools/va_res/page.py`, `tools/va_res/report.py`

### 19.6 Tinh chỉnh Prompt VaRES — Đúng bản chất Complacency

**Vấn đề:** AI hiểu nhầm "Complacency Index thấp = thị trường an toàn".

**Fix trong `promt/va_res_promt.md`:**
- Thêm section `# LƯU Ý QUAN TRỌNG VỀ CÁCH HIỂU COMPLACENCY INDEX`
- Complacency chỉ xảy ra 2 regime: Phân phối đỉnh + Tích lũy đi ngang
- Complacency thấp KHÔNG đồng nghĩa an toàn (có thể đang hoảng loạn/sụp đổ/uptrend)
- Tuyệt đối không viết "thị trường bình thường" chỉ vì Complacency thấp

### 19.7 Data Pipeline — Smart Incremental Refactor

**Vấn đề:** Mỗi ngày cron tải lại toàn bộ lookback (~3 năm) → chậm, dễ hit rate limit.

**Giải pháp:**
- `command/update_data.py`: refactor thành incremental + backfill mode
  - **Incremental (default):** Đọc file cũ, chỉ tải từ `last_date - 3 ngày` → `today`, merge bằng `combine_first()`
  - **`--backfill N`:** Tải N ngày lịch sử
  - **`--from-date YYYY-MM-DD`:** Tải từ ngày cụ thể
- `config.py`: thêm `DEFAULT_BACKFILL_DAYS = 2190` (~6 năm)
- `.github/workflows/update_pipeline.yml`: thêm `workflow_dispatch` inputs `backfill_days` + `from_date`

**Kết quả test:** Incremental chạy 251 mã × 6 ngày ≈ 5 phút. Market_data mở rộng từ 925 → 1708 ngày (~7 năm, 2019–2026).

### 19.8 Tạo tool mới: Var-CVaR(ES) VNINDEX (Tool #9)

**Yêu cầu:** Tool chỉ focus VNINDEX, tính rolling σ30, Parametric VaR 95%, Historical VaR 3 năm, ES 95%.

**Files mới:**
- `tools/var_cvar_vnindex/quant/metrics.py`: `calculate_var_cvar_metrics()` — log-return, σ30, Param VaR (z=-1.645), Historical VaR (rolling 5th percentile, 756 ngày), ES (mean of tail ≤ VaR)
- `tools/var_cvar_vnindex/ui/sidebar.py`: Date picker + AI provider + API key
- `tools/var_cvar_vnindex/ui/charts.py`: Plotly 4 traces (σ, Param VaR, Hist VaR, ES + fill)
- `tools/var_cvar_vnindex/page.py`: Compute → session_state → display (lọc theo plot_start_date) + AI block
- `tools/var_cvar_vnindex/report.py`: `snapshot()` cho AI CIO
- `pages/9_Var_CVaR_VNINDEX.py`: Entry page
- `promt/var_cvar_vnindex_promt.md`: AI prompt — so sánh Parametric vs Historical VaR, đánh giá ES spread, fat tail

**Files sửa:**
- `shared/ai_cio.py`: thêm `run_var_cvar_vnindex()`, executive summary → 9 báo cáo
- `promt/executive_summary_promt.md`: thêm section 9 (toán học Var-CVaR)
- `app.py`: spinner "9 báo cáo"
- `docs/skill.md`: cập nhật danh sách tool

**Kết quả test:**
```
VNINDEX: 1,915.37 | σ30: 1.22% | Param VaR: -1.43% | Hist VaR: -1.64% | ES: -3.00%
```

### 19.9 Module B VaRES — Thêm chi tiết kết quả tính toán

**Thay đổi:**
- Thêm 3 metrics cards (Tổng mã VN30, Số mã thủng VaR, Stress Index)
- Thêm top 3 breach margin chi tiết (ticker + margin% + return% + VaR%)
- Bảng trạng thái thêm cột Breach Margin (%)

**File sửa:** `tools/va_res/page.py`

### 19.10 Module C VaRES — Bỏ phân ngành, dùng toàn bộ universe

**Thay đổi:**
- Bỏ `MARKET_TICKERS` dict hardcode, `ALL_MARKET_TICKERS` list
- Universe = toàn bộ columns trong `market_data.csv` (trừ date_col và VNINDEX)
- Bảng kết quả bỏ cột "Ngành"
- Bỏ `benchmark_ticker` trong `get_latest_risk_status()` (vì Self-Baseline không cần benchmark)

**File sửa:** `tools/va_res/page.py`, `tools/va_res/quant/metrics.py`

### 19.11 Fix plot_start_date không phản ứng trong VaRES

**Nguyên nhân:** `st.button` chỉ return True 1 lần. Khi đổi ngày trong sidebar, script rerun, button về False, block tính toán + vẽ không chạy lại.

**Fix:** Refactor tách tính toán (lưu session_state khi bấm button) và hiển thị (đọc từ session_state + lọc theo plot_start_date) cho cả 3 module A/B/C.

**File sửa:** `tools/va_res/page.py`

---

## 20) Nguyên tắc làm việc tiếp theo (cập nhật)

- AI CIO hiện tại tổng hợp **9 phòng ban** (Fear Greed, Manipulation, Dispersion, Upside Ratio, Risk Adjusted Growth, Market Breadth, ESR Monitor, VaRES Engine, Var-CVaR VNINDEX)
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
- **Data pipeline**: Incremental daily + Backfill qua `--backfill` / `--from-date` / workflow_dispatch
- Nguồn data chính: **VCI**, fallback **KBS**
- Report duy nhất trên app: **PDF Export của AI CIO** (thay thế screenshot PDF)
- COE mặc định: **14%**
- **Không hardcode đường dẫn tuyệt đối theo OS** (Windows/macOS); luôn dùng `ROOT_DIR` hoặc `Path(__file__)`
- **Font PDF:** dùng `fpdf2` + font `DejaVuSans` trong `fonts/` (không dựa vào system font)

---

## 24) Phiên cập nhật 2026-05-11 — Shortcut API Key 4 số + Xóa GitHub Sync tự động

### 24.1 Mục tiêu

1. **Shortcut API Key:** Cho phép người dùng gõ 4 số (VD: `1234`) thay vì copy-paste API Key dài. Key thật được lưu trong Streamlit Cloud Secrets.
2. **Xóa GitHub Sync tự động:** App không còn tự động push file lên GitHub sau mỗi lần chạy AI/tool → tránh vòng lặp reload trên Streamlit Cloud.

### 24.2 File tạo mới

**`shared/api_key_helper.py`** — Hàm `resolve_api_key()` dùng chung cho toàn platform.

### 24.3 Cấu hình Streamlit Secrets

Thêm trong **Streamlit Cloud Dashboard → App → Settings → Secrets**:
```toml
AI_KEY_1234=sk-thực_tế_của_bạn...
AI_KEY_5678=sk-thực_tế_khác...
```

### 24.4 Cách hoạt động

Trên tất cả ô nhập API Key:
- Gõ `1234` → lookup `st.secrets["AI_KEY_1234"]` → ✅ "Đã dùng shortcut 1234"
- Gõ `5678` → ✅
- Gõ `sk-xxx...` → dùng key thật
- Gõ số 4 digit không tồn tại → ❌ báo lỗi

### 24.5 Danh sách file đã xử lý

| File | Thay đổi |
|------|----------|
| **`shared/api_key_helper.py`** | **Mới** — Hàm `resolve_api_key()` dùng chung |
| **`app.py`** | Import alias `_resolve_api_key`, áp dụng AI CIO |
| **`tools/dispersion/ui/sidebar.py`** | Import + dùng `resolve_api_key` |
| **`tools/fear_greed/ui/sidebar.py`** | Import + dùng `resolve_api_key` |
| **`tools/manipulation/ui/sidebar.py`** | Import + dùng `resolve_api_key` |
| **`tools/market_breadth/ui/sidebar.py`** | Import + dùng `resolve_api_key` |
| **`tools/risk_adjusted_growth/ui/sidebar.py`** | Import + dùng `resolve_api_key` |
| **`tools/upside_ratio/ui/sidebar.py`** | Import + dùng `resolve_api_key` |
| **`tools/esr_monitor/page.py`** | Import + dùng `resolve_api_key` + **xóa GitHub sync tự động** |
| **`tools/va_res/page.py`** | Import + dùng `resolve_api_key` + **xóa GitHub sync tự động** |
| **`tools/var_cvar_vnindex/page.py`** | Import + dùng `resolve_api_key` + **xóa GitHub sync tự động** |

### 24.6 GitHub Sync tự động đã xóa

Đã xóa block sau khỏi 3 file page (esr_monitor, va_res, var_cvar_vnindex):
```python
try:
    from shared.github_sync import upload_file
    ...
    upload_file(...)
except:
    ...
```

**Kết quả:** Không còn commit tự động → GitHub không thay đổi → Streamlit Cloud không reload liên tục.

Vẫn giữ expander **"🔧 Kiểm tra & Đồng bộ GitHub"** ở cuối trang chủ để sync thủ công khi cần.

### 24.7 Pattern cho tool mới trong tương lai

```python
from shared.api_key_helper import resolve_api_key

api_key_raw = st.text_input("API Key (hoặc shortcut 4 số):", type="password",
    placeholder="sk-... hoặc 4 số",
    help="Gõ API key thật (sk-...) hoặc shortcut 4 số đã lưu trong Streamlit Secrets (VD: 1234)")
api_key, api_key_msg, api_key_err = resolve_api_key(api_key_raw)
if api_key_err:
    st.error(api_key_msg)
elif api_key_msg:
    st.success(api_key_msg)
```

---

## 25) Phiên cập nhật 2026-05-11 (tiếp) — ESR Monitor Refactor 5-Pillar Full

### 25.1 Mục tiêu

Port hoàn chỉnh ESR Monitor từ `Desktop/9999/ESR monitor/ESR.app.py` vào framework chuẩn, thay thế proxy cũ.

### 25.2 Thay đổi chính

**`tools/esr_monitor/quant/metrics.py` — Viết lại 100%**
- Xóa hàm `calculate_esr()` (proxy 3 pillar)
- Thêm:
  - `VN30_TICKERS`: tuple 30 mã chuẩn
  - `PillarEngine`: 5 pillar gốc (`s_vol`, `s_pressure`, `s_correlation`, `s_liquidity`, `s_valuation`) + 3 downside variant + `compute_all()`
  - `SSIResult`: dataclass chứa `ssi`, `weights_history`, `pca_concentration`, `ranks`
  - `SSIAggregator`: Expanding-window PCA(1) rank-based, look-ahead-free, sign-aligned
  - `HMMRegimeClassifier`: 2-state Gaussian HMM + `implied_threshold()` (quadratic formula)
  - `MARKET_STATES`: 4-state dict (EUPHORIC_RISK, ACTIVE_STRESS, HEALTHY, CALM_CORRECTION)
  - `classify_market_state()`: kết hợp HMM regime + trend MA200
  - `run_esr_pipeline()`: full pipeline từ raw data → (pillars, SSIResult, market_states, threshold)

**`tools/esr_monitor/ui/charts.py` — Viết lại 100%**
- Xóa `render_esr_chart(df)` cũ
- Thêm:
  - `render_esr_chart()`: 2 panel (SSI+index, PCA EVR), 4-state shading, HMM threshold + hrect, trend MA, manual thresholds fallback
  - `render_pillar_diagnostics()`: expander với 3 tabs

**`tools/esr_monitor/page.py` — Refactor toàn bộ**
- Sidebar mới: PCA warmup (252), EMA span (20), deposit rate (6%), pillar mode radio, trend MA (200), HMM checkbox
- Header metrics: Market Regime card (4-state color/emoji), PCA Concentration, state dist %, PCA weights bar chart
- Chart: render_esr_chart() mới với HMM overlay
- Diagnostics: render_pillar_diagnostics() expander
- AI analysis: dùng dữ liệu mới (SSI từ result.ssi, EVR, market state, threshold...)

**`tools/esr_monitor/report.py` — Cập nhật**
- Dùng `run_esr_pipeline()` thay `calculate_esr()`
- Thêm: `pca_concentration`, `pca_weights`, `n_tickers`

**`shared/ai_cio.py` — Cập nhật**
- Import: `run_esr_pipeline` thay `calculate_esr`
- `run_esr_monitor()`: dùng pipeline mới, thêm EVR, market state, threshold vào prompt
- Xóa GitHub auto-sync trong `_write_cache()`

### 25.3 Prompt template

Prompt đã cập nhật (thêm `[PCA_EVR]`, `[Market State]`, `[Pillar Mode]`, `[Threshold]`):
- `promt/ESR monitor promt.md`

### 25.4 Lưu ý

- Có thể dùng volume proxy flat (1e9) do data_lake không có real volume
- Amihud chỉ mang tính tương đối, không phải absolute
- Downside mode mặc định (chỉ tính vol/corr/liq trên phiên giảm) — được khuyến nghị
- PCA warmup = 252 ngày ~ 1 năm dữ liệu trước khi có SSI đầu tiên

---

## 26) Phiên cập nhật 2026-05-14 — Fed Liquidity Monitor (Nhánh A — Macro)

### 26.1 Mục tiêu

Port tool Fed Liquidity từ `Desktop/9999/fed/` (file `fed.py` + `feddashborad.py`) vào platform mới theo skeleton chuẩn. Đây là tool đầu tiên của nhánh **A_Macro_Analysis**.

### 26.2 File tạo mới

| File | Nội dung |
|------|----------|
| `tools/fed_liquidity/__init__.py` | Empty |
| `tools/fed_liquidity/quant/__init__.py` | Empty |
| `tools/fed_liquidity/quant/metrics.py` | `fetch_fed_data(api_key)`, `process_liquidity_logic(df_raw)`, `summarize_latest(df)` + constants |
| `tools/fed_liquidity/ui/__init__.py` | Empty |
| `tools/fed_liquidity/ui/sidebar.py` | `render_sidebar()` — date picker + clear cache |
| `tools/fed_liquidity/ui/charts.py` | `plot_net_liquidity()`, `plot_momentum()`, `plot_zscore()` (Plotly) |
| `tools/fed_liquidity/page.py` | `render()` — header metrics + 3 chart + bảng + AI block |
| `tools/fed_liquidity/report.py` | `snapshot()` đọc cache CSV |
| `command/update_fed_liquidity.py` | Updater: pull FRED → process → save CSV |
| `promt/fed_liquidity_promt.md` | AI prompt Global Macro Strategist |
| `pages/tools_page_A/__init__.py` | Empty |
| `pages/tools_page_A/_1_Fed_Liquidity.py` | Entry — gọi `tools.fed_liquidity.page.render()` |

### 26.3 File sửa

- `pages/A_Macro_Analysis.py`: Refactor từ placeholder → grid menu pattern (giống `C_Behavioral_Finance.py`)
- `config.py`: Thêm `FED_LIQUIDITY_DATA = DATA_LAKE / "fed_liquidity_cache.csv"` và `FRED_API_KEY = os.getenv("FRED_API_KEY", "")`
- `docs/skill.md`: Thêm section 3.10 + 5.5 + section 26 này

### 26.4 Quy trình vận hành

1. **Set FRED API key**: thêm `FRED_API_KEY=xxx` vào `.env` (hoặc `export FRED_API_KEY=xxx`)
2. **Update cache**: `python command/update_fed_liquidity.py`
3. **Mở app**: `streamlit run app.py` → trang `📈 Phân tích Vĩ mô` → 🏦 Fed Liquidity Monitor

### 26.5 Lưu ý kỹ thuật

- **App đọc cache, không gọi FRED API trực tiếp** — đúng pattern data_lake
- Updater là pipeline đầy đủ: pull → process → save, không tách stage để giảm I/O
- `fredapi>=0.5.2` đã thêm vào `requirements.txt` (Streamlit Cloud + GitHub Actions tự cài)
- AI prompt theo template "[Placeholder]" giống `var_cvar_vnindex_promt.md` để page.py replace dễ
- Cache AI text: `daily_cache/fed_liquidity_{provider}_{ddmmyy}.txt` — đồng nhất với các tool khác
- **Chưa tích hợp vào AI CIO Executive Summary** (weekly data, frequency khác 9 tool daily) — sẽ cân nhắc thêm sau nếu cần

---

## 27) Phiên cập nhật 2026-05-15 — Chuẩn hóa History & Module Backtest

### 27.1 Chuẩn hóa History Navigation (Toàn hệ thống)

- **Module mới:** `shared/history_selector.py` — chứa hàm `build_history_options()` để tự động quét thư mục cache, parse ngày từ filename (`ddmmyy`) và trả về danh sách dropdown được sắp xếp từ **mới nhất đến cũ nhất**.
- **Phạm vi áp dụng:** Đã refactor toàn bộ 10 công cụ (Fear & Greed, ESR, Dispersion, Breadth, Upside Ratio, VaRES, Var-CVaR, Fed Liquidity, v.v.). 
    - Loại bỏ logic sắp xếp theo `st_mtime` (không ổn định).
    - Đồng nhất giao diện: Dropdown chọn ngày phân tích cũ luôn hiển thị ngày gần nhất làm mặc định.
- **Workflow Scheduling:** Cập nhật GitHub Actions (`update_pipeline.yml` và `ai_cio_daily.yml`) chạy vào **14:30 và 14:45 (giờ VN)** hàng ngày để khớp với giờ đóng cửa thị trường.
- **AI CIO Report:** Fix mặc định hiển thị ngày gần nhất trong ô chọn report tại trang chủ.
- **History Score & Regime:** Thêm trang hiển thị bảng lịch sử điểm số AI CIO từ `Ai_cio_report.csv` kèm biểu đồ đường.
- **Dispersion Universe:** Xác nhận sử dụng toàn bộ tickers trong `market_data.csv`.
- **UI Small Fix:** Tối ưu kích thước bảng và biểu đồ tại trang History Score để hiển thị đầy đủ thông tin trên màn hình nhỏ.
- **Workflow Logic:** Xác nhận AI CIO luôn chạy lại Quant Engine mới nhất nếu chưa có cache hôm nay, đảm bảo dữ liệu "fresh".
- **Universe:** Tickers cho Dispersion và các tool breadth là toàn bộ 400+ mã trong `tickers.csv`.
- **Workflow Chronology:** Data Update (14:30) -> AI CIO Report (14:45).
- **History Selector Standard:** Luôn sắp xếp `ddmmyy` reverse-chronological.
- **Standardized Dropdowns:** Mặc định chọn ngày gần nhất cho mọi tab Xem lại phân tích cũ.
- **UI UX:** Thêm nút "📊 History Score" và "⚖️ Backtest Strategy" tại trang Behavioral Finance.
- **AI CIO Report Logic:** Đảm bảo data fresh bằng cách re-run quant engine nếu cache ngày hiện tại chưa tồn tại.
- **History Score Page:** Hiển thị dữ liệu từ `Ai_cio_report.csv` với biểu đồ Line Chart.
- **Adaptive Data Loading:** Cập nhật các tool core (VaR, Breadth) để hỗ trợ `min_periods`, cho phép chạy với dữ liệu ngắn mà không crash.
- **Backtest Proposal:** Đã soạn thảo và lưu tại `docs/backtest_proposal.md`.
- **GitHub Workflow:** Cron schedule 14:30 (07:30 UTC) và 14:45 (07:45 UTC) từ thứ 2 đến thứ 6.
- **Universe Scope:** Khẳng định Dispersion dùng toàn bộ market_data.csv.

### 27.2 Module Backtest (Mới)
- **Kiến trúc 3 tầng:**
  - **Tầng 1 (Composite Signal):** `tools/backtest/quant/composite_signal.py` — Gộp 4 trụ cột: Fear&Greed, Market Breadth, ESR SSI, và VaR/CVaR (Expected Shortfall).
  - **Tầng 2 (Allocation):** `tools/backtest/quant/allocation.py` — Score 0-100 → Tỷ lệ Equity/Cash.
    - Đặc biệt: **Score 0-10 (Capitulation) -> 90% Equity**; **Score 85-95 (Bubble) -> 10% Equity**.
  - **Tầng 3 (Engine):** `tools/backtest/quant/engine.py` — Tính lợi nhuận, phí giao dịch (0.3%), Sharpe, CAGR, MaxDD.
- **Tính năng Adaptive:** Module Backtest tự tính toán Breadth và VaR với `min_periods=1` để có thể chạy ngay cả khi dữ liệu lịch sử ngắn (ví dụ từ tháng 7/2020), trong khi các tool con nguyên bản vẫn giữ cửa sổ chuẩn (3 năm).
- **UI Backtest:** `tools/backtest/page.py` — Dashboard với Equity Curve, Drawdown Chart, và Regime Allocation Overlay.
- **ValueError Fix:** Đã thêm xử lý làm sạch dữ liệu (`replace inf with nan`, `ffill`, `bfill`) để tránh lỗi trong quá trình tính toán PCA và log-return.
- **Default Range:** Thiết lập mặc định 07/2020 - 02/2024 theo yêu cầu kiểm thử giai đoạn biến động mạnh.
- **Backtest UI:** Tích hợp trực tiếp vào nhánh Behavioral Finance.
- **Metrics:** CAGR, Sharpe Ratio, Max Drawdown, Win Rate, Total Return.
- **Chart:** Plotly interactive charts (Equity Curve, Drawdown, Allocation).
- **Signal Logic:** Adaptive windows (min_periods=1) cho dữ liệu ngắn.
- **Cleaning:** Robust NaN/Inf handling cho PCA stability.
- **Allocation Regimes:** Capitulation (0-10), Fear (10-25), Caution (25-45), Neutral (45-65), Greed (65-85), Bubble (85-95), Blow-off Top (95-100).
- **Rebalance:** Tín hiệu thay đổi -> giao dịch, khấu trừ phí 0.3%.
- **Benchmark:** VNINDEX Buy & Hold.
- **Backtest Proposal:** Đã copy vào thư mục `docs/`.
- **History Standardized:** Toàn bộ platform đã dùng `shared/history_selector.py`.
- **Scheduler:** 14:30 (Data) -> 14:45 (AI CIO) VN Time.
- **History Score Page:** Đã được thu nhỏ layout để hiển thị đầy đủ nội dung.
- **AI CIO Date Selection:** Mặc định ngày gần nhất trên app.py.
- **Tool Navigation:** Chuẩn hóa dropdown chọn ngày cũ.
- **Universe Confirmation:** Dispersion dùng toàn bộ mã trong market_data.csv.
- **Backtest Availability:** Có sẵn tại C_Behavioral_Finance.py.
- **Signal Resilience:** Tự tính toán logic phụ trợ trong backtest module để giữ core tools nguyên bản.
- **Data Cleaning:** Xử lý `ValueError: Input X contains infinity` triệt để.
- **Documentation:** Cập nhật đầy đủ `docs/skill.md` và `docs/backtest_proposal.md`.

---

## 28) Phiên cập nhật 2026-05-15 — Backtest Tuning Sâu + Fix HMM Look-ahead trong ESR

### 28.1 Bối cảnh

Tiếp tục từ section 27 (module backtest mới + fix `Input X contains infinity`), phiên này tập trung:
1. Tinh chỉnh allocation engine để đạt Sharpe > B&H trên multi-period
2. Phát hiện và fix look-ahead bias trong HMM regime classifier
3. Phân biệt 2 use case: **live ESR Monitor** vs **backtest fidelity**

### 28.2 Fix gốc rễ — Inf từ giá zero

- **Triệu chứng:** `Input X contains infinity or a value too large for dtype('float64')` khi chạy backtest.
- **Nguyên nhân:** `data_lake/market_data.csv` chứa 5 giá trị `0`. `pct_change(0 → x) = inf` → vào `extract_market_factor_pca` (`tools/fear_greed/quant/factors.py`), `clean.fillna(0)` không loại được `inf` → `sklearn.PCA` crash.
- **Fix:**
  - `composite_signal.py`: thêm `replace([np.inf, -np.inf, 0], np.nan)` trước `ffill/bfill/dropna(axis=1, how='all')`.
  - `factors.py`: thêm `replace([np.inf, -np.inf], np.nan)` trước `fillna(0)` + guard `pc1.std() > 0` để tránh nhân vô cực khi PC1 suy biến.

### 28.3 Allocation Engine — Refactor 3-tầng

**Tầng 1 — Composite Signal** ([composite_signal.py](tools/backtest/quant/composite_signal.py)):
- Bỏ EWM(span=5) cuối (double-smoothing lag, F&G đã smooth sẵn).
- Mean của 4 signal: `fear_greed + breadth + ssi_greed + var_stress`.

**Tầng 2 — Allocation Curve** ([allocation.py](tools/backtest/quant/allocation.py)):
- Bỏ grid 7 bậc cũ (vách đá 75% → 10%), thay bằng **logistic smooth curve**:
  ```python
  equity = EQ_MIN + (EQ_MAX - EQ_MIN) / (1 + exp((score - 50) / 12))
  # EQ_MIN=0.05, EQ_MAX=0.95, contrarian
  ```
- **TREND_BOUNDS** overlay từ ESR Market_State (sau nhiều iteration tune):
  - `HEALTHY`: floor 0.85 (bull confirmed)
  - `EUPHORIC_RISK`: floor **0.80** (đầu phiên 0.50 quá defensive → bỏ lỡ bull tail)
  - `CALM_CORRECTION`: floor 0.40
  - `ACTIVE_STRESS`: **cap 0.30** (revert từ floor 0.60 sau khi fix HMM lag, không còn cần compensation)

**Tầng 3 — Engine** ([engine.py](tools/backtest/quant/engine.py)): không đổi.

### 28.4 MA200 Hard Cap (đột phá lớn nhất)

- **Hằng số:** `MA200_HARD_CAP = 0.10` — khi `VNINDEX < MA200` thì equity ≤ 10%, ghi đè mọi rule khác.
- **Hysteresis ±2% chống whipsaw**:
  - Kích hoạt cap: `price < MA200 × (1 - buffer)`
  - Thả cap: `price > MA200 × (1 + buffer)`
  - Vùng giữa: giữ trạng thái cũ.
  - Sweep buffer: 1% Pareto-optimal, 2% conservative trade-off.
- Slider UI cho phép experiment 0–5%.
- **V-shape early release** (đã code nhưng tắt mặc định `VSHAPE_THRESHOLD = 0.0`):
  - Sweep cho thấy threshold thấp gây whipsaw nặng (fee 13%/period), threshold cao gần như không trigger.
  - Strategy không phân biệt được V-shape thật và bounce giả real-time.
  - Code giữ lại để thử confirmation signal sau (price > MA50, etc.).

### 28.5 Diagnostic Layer + UI Backtest

[tools/backtest/page.py](tools/backtest/page.py):
- Metric comparison **Strategy vs B&H** từng chỉ số (CAGR/Sharpe/MaxDD/Win Rate).
- Drawdown chart overlay strategy + B&H.
- Allocation chart 3 đường: `base` (composite) / `equity_post_regime` / `equity_weight` (final).
- Background shading theo 4-state regime.
- Diagnostic table: trend overlay activation, equity distribution, **avg equity & forward return per regime** — phơi bày HMM lag.
- Slider sidebar: `MA200 hysteresis buffer`, `V-shape early release threshold`.

### 28.6 Fix look-ahead HMM trong ESR Monitor (đột phá thứ hai)

**Vấn đề phát hiện qua diagnostic:**
- `HMMRegimeClassifier.fit_predict` fit trên **toàn bộ SSI history**, rồi predict ngược lại trên cùng data → **look-ahead bias chuẩn**.
- Mọi backtest dùng `market_state` đang **lạc quan hơn thực tế** vì regime label "biết tương lai".
- Đặc biệt: SSI Aggregator là expanding-window (look-ahead-free) nhưng tầng HMM bên trên thì không → người dùng dễ tin nhầm cả pipeline là clean.

**Giải pháp — 3 classifier coexist:**

[esr_monitor/quant/metrics.py](tools/esr_monitor/quant/metrics.py):

| Classifier | Look-ahead? | Use case |
|---|---|---|
| `HMMRegimeClassifier.fit_predict` (full-fit) | ❌ Có | LIVE view (xem regime hôm nay) — detection quality cao nhất |
| `HMMRegimeClassifier.fit_predict_walk_forward` | ✅ Sạch | Backtest fidelity, history view |
| `RuleBasedRegimeClassifier` | ✅ Sạch | Alternative đơn giản, không cần hmmlearn |

**Walk-forward HMM logic:**
- Refit HMM mỗi `refit_every` (default 60 ngày).
- Tại mỗi refit point t: fit trên `ssi[:t]` → predict cho `ssi[t : t + refit_every]`.
- Giữ model cuối để `implied_threshold()` vẫn hoạt động.

**Rule-based logic** (tuned cho VN sau sweep):
- `percentile_threshold = 0.60` (top 40% expanding rank → HIGH stress)
- `absolute_threshold = 0.65` (level fallback song song với rank)
- `smooth k/n = 2/3` (responsive, 3/5 quá strict)
- Logic: `HIGH = (rank > pct) OR (SSI > absolute)`

### 28.7 Phân biệt LIVE vs BACKTEST use case

**Quan sát của user về visual quality:**
- HMM full-fit catch EUPHORIC_RISK 2021 (pre-crash buildup), ACTIVE_STRESS Apr–Dec 2022, shock Apr 2025, HEALTHY uptrend 2025→nay.
- Rule-based v1 (pct=0.70) miss crash 2022 (45/105 ngày AS).
- Rule-based v2 (pct=0.60+abs=0.65) catch tốt hơn (52/105) nhưng vẫn kém HMM (66/105).

**Kết luận:** look-ahead bias chỉ harmful cho backtest, KHÔNG harmful cho live view (làm gì có tương lai để leak).

**Default sau khi resolve:**
- **ESR Monitor tool (live view)**: `regime_method='hmm'` (full-fit) — best visual.
- **Backtest pipeline** (`composite_signal.py`): `regime_method='hmm_walk_forward'` — best fidelity.
- User toggle qua sidebar dropdown.

### 28.8 Tinh chỉnh ACTIVE_STRESS overlay — compensation đan xen

User chỉ ra: lúc HMM còn lag, đảo `ACTIVE_STRESS = cap 0.30 → floor 0.60` để "buy lagged-bottom". Khi fix HMM lag → compensation cũ không còn cần thiết.

**Test 4 combo (HMM/rule × cap/floor):**
- Với HMM: cap 0.30 thắng floor 0.60 ở Period B (CAGR +0.64, Sharpe +0.06).
- Với rule-based: cả 2 ra kết quả y hệt (MA200 hard cap đè lên).

→ Revert về cap 0.30 cho logic sạch. Label `STRESS_BUY` → `BEAR_CAP`.

### 28.9 Performance Summary

**3 period test (Period A: 2020-07→2024-02, B: 2024-07→2026-05, C: full 5.8y):**

| Config | A CAGR/Sharpe/DD | B CAGR/Sharpe/DD | C CAGR/Sharpe/DD |
|---|---|---|---|
| Grid 7-bậc cũ (baseline) | 6.88 / 0.62 / -21.1 | 5.72 / 0.55 / -11.0 | — |
| + Logistic + Trend overlay + MA200 cap (HMM look-ahead) | 11.88 / 1.04 / -27.9 | 10.81 / 0.78 / -13.6 | 10.68 / 0.87 / -27.9 |
| + Rule-based v1 (fix look-ahead) | 12.50 / 1.05 / -23.7 | 11.52 / 0.80 / -14.2 | 11.29 / 0.88 / -23.7 |
| **+ HMM walk-forward (final)** | **11.84 / 1.02 / -23.7** | **11.39 / 0.83 / -12.7** | **10.84 / 0.87 / -23.7** |
| B&H VNINDEX (reference) | 12.16 / 0.60 / -40.3 | 24.60 / 1.25 / -18.1 | 15.05 / 0.76 / -40.3 |

**Verdict:** Sharpe combined 0.87 vs B&H 0.76 (thắng risk-adjusted trên 5.8y). MaxDD giảm 12.4 điểm vs B&H. CAGR kém B&H 4.2pt — trade-off chấp nhận được cho defensive long-only.

### 28.10 File thay đổi

**Core code:**
- `tools/backtest/quant/composite_signal.py`: cleanup inf/zero, MA200 hysteresis (`_below_ma200_with_hysteresis`), V-shape (disabled default), ESR pipeline với `regime_method='hmm_walk_forward'`.
- `tools/backtest/quant/allocation.py`: logistic curve (`smooth_equity_from_score`), `TREND_BOUNDS` 4-state, `MA200_HARD_CAP`, output đầy đủ diagnostic columns.
- `tools/backtest/quant/engine.py`: không đổi (kế hoạch sau: Sharpe robust, win rate fallback).
- `tools/backtest/page.py`: UI mới với metric vs B&H, multi-line allocation chart, diagnostic table, sliders MA200 buffer + V-shape.
- `tools/esr_monitor/quant/metrics.py`: 
  - `RuleBasedRegimeClassifier` (look-ahead-free, percentile + absolute threshold)
  - `HMMRegimeClassifier.fit_predict_walk_forward()` + `analyze(walk_forward=True)`
  - `run_esr_pipeline()` thêm `regime_method` (3 options) + tham số liên quan
- `tools/esr_monitor/page.py`: sidebar 3-option dropdown classifier, slider tham số rule-based + walk-forward refit interval.
- `tools/fear_greed/quant/factors.py`: NaN-safety trước PCA, guard pc1.std() > 0.

### 28.11 Bài học method

1. **Compensation đan xen nguy hiểm**: rule "đảo ACTIVE_STRESS = floor" được tạo để bù HMM lag, khi fix HMM thì compensation trở thành noise/sai. Cần document rõ rule tồn tại để bù cái gì, revisit khi root cause được fix.
2. **Diagnostic insight ≠ predictable signal**: bench dương trung bình +0.38%/ngày trong cap không phải actionable signal (V-shape thử nghiệm thất bại — strategy không phân biệt được V-shape thật vs bounce giả real-time).
3. **Tách live vs backtest use case**: cùng 1 algorithm có thể đúng cho use case này, sai cho use case kia. HMM look-ahead OK cho live, sai cho backtest.
4. **Period dependency cảnh báo**: strategy thắng B&H trong Period A (có crash) nhưng kém B&H trong Period B (bull thuần) → không thể chọn period trong production. Cần test cả 2 trước khi tin metrics.

### 28.12 Status quỹ thực tế

- **Sharpe combined 5.8y = 0.87** (vs B&H 0.76) → đạt mức Quant Fund Tier B.
- CAGR underperform B&H 4.2pt nhưng MaxDD better 12.4pt → defensive long-only acceptable.
- Vẫn cần trước khi commit vốn:
  - **Out-of-sample test 2017-2020** (sideways)
  - **Walk-forward validation** allocation params
  - **Universe survivorship-free** (snapshot quý)
  - **Cash yield 5%/năm** (Period B giữ 34% cash chưa tính lãi)
  - **Live paper trading** tối thiểu 6 tháng

### 28.13 PRODUCTION_REGIME_METHOD — Single Source of Truth

Sau khi triển khai 3 classifier, cần đảm bảo **AI CIO AUTO + ESR Monitor LIVE + report snapshot dùng cùng setting** để regime hiển thị nhất quán toàn hệ thống. Bổ sung constant trong `tools/esr_monitor/quant/metrics.py`:

```python
PRODUCTION_REGIME_METHOD = 'hmm'  # default cho live paths
```

**Callers đồng bộ:**
- `shared/ai_cio.py::run_esr_monitor` — AI CIO AUTO + Manual
- `tools/esr_monitor/report.py::snapshot` — machine-readable CSV report
- `tools/esr_monitor/page.py` — sidebar default cho ESR Monitor UI (gắn label `⭐ PRODUCTION`)

**Caller riêng (intentional khác):**
- `tools/backtest/quant/composite_signal.py` — hardcode `'hmm_walk_forward'` cho backtest fidelity (look-ahead-free).

→ Đổi `PRODUCTION_REGIME_METHOD` ở 1 chỗ = mọi live path tự đổi theo. Backtest pipeline isolated.

### 28.14 Roadmap đề xuất tiếp

1. ✅ Fix HMM look-ahead (xong section này)
2. ✅ Đồng bộ AI CIO AUTO với ESR Monitor (PRODUCTION_REGIME_METHOD)
3. ⏭️ Universe snapshot quý (mở fidelity cho Breadth/Dispersion/Manipulation)
4. ⏭️ EGARCH fallback trong Fear & Greed (tránh production crash)
5. ⏭️ Cornish-Fisher cho Var-CVaR VNINDEX (tail risk)
6. ⏭️ Dynamic COE theo lãi suất
7. ⏭️ Validate Dispersion/Manipulation/Upside Ratio alpha trong composite
