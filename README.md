# 📊 Quant Platform

Nền tảng phân tích định lượng (Quantitative Analysis) đa chiều cho thị trường chứng khoán Việt Nam, được xây dựng trên **Streamlit**.

🔗 **Deploy trên Streamlit Cloud**: [Hướng dẫn bên dưới](#-deploy-lên-streamlit-cloud)

---

## 🚀 Kiến trúc tổng quan

Platform được tổ chức thành **3 nhánh phân tích chính**:

| Nhánh | Mô tả | Số công cụ |
|-------|-------|------------|
| 📈 **Macro Analysis** | Phân tích vĩ mô toàn cầu & Việt Nam | 5 tools |
| 🔬 **Micro Analysis** | Phân tích vi mô, pairs trading, factor examination | 2 tools |
| 🧠 **Behavioral Finance** | Tài chính hành vi, tâm lý thị trường, rủi ro hệ thống | 9+ tools |

---

## 📈 Macro Analysis — Phân tích Vĩ mô

| # | Công cụ | Mô tả |
|---|---------|-------|
| 1 | **Fed Liquidity Monitor** | Net Liquidity (WALCL − TGA − RRP) + Impulse EMA + Z-Score 52W → Tín hiệu ADD/CUT/HOLD |
| 2 | **Global Financial Conditions** | VIX + MOVE + HY OAS + CCC OAS · Static PCA composite · Regime via PC1 percentile rank 3Y |
| 3 | **VNIBOR Monitor** | Lãi suất liên ngân hàng qua đêm và các kỳ hạn ngắn · Phân loại trạng thái thanh khoản |
| 4 | **Liquidity Transmission (LTMM)** | Theo dõi kênh truyền dẫn thanh khoản: Thượng nguồn → Lớp ma sát → Hạ nguồn |
| 5 | **VN100 Earnings Health** | Fundamental earnings monitor VN100: Momentum + Breadth + Stability 12Q + Profitability + PCA validation |

---

## 🔬 Micro Analysis — Phân tích Vi mô

| # | Công cụ | Mô tả |
|---|---------|-------|
| 1 | **Pairs Trading Research Lab** | Cointegration (Engle-Granger + Johansen) + OU half-life + Z-score 60d trên 7 cluster VN |
| 2 | **Portfolio Factor Examination** | Multi-factor cross-sectional scorer (10 factors): Mom/LowVol/Beta/IdioVol/Liquidity/Size/Anti-Lottery/Reversal |

---

## 🧠 Behavioral Finance — Tài chính Hành vi

| # | Công cụ | Mô tả |
|---|---------|-------|
| 1 | **Market Sentiment (Fear & Greed)** | PCA & EGARCH(1,1,1) Skewed-T, Kelly Skewness — Đo lường tâm lý thị trường |
| 2 | **Upside/Downside Ratio** | Hybrid MC Bidirectional Breadth Model — Phân tích Cung-Cầu với Monte Carlo ensemble |
| 3 | **Risk-Adjusted Growth** | Phân tích tăng trưởng điều chỉnh rủi ro — DCF, P/B, Cash Payout cho ngân hàng |
| 4 | **Market Breadth** | Độ rộng thị trường — Số mã >MA20/60/125/252, Top 10 Volume Leaders |
| 5 | **ESR Monitor** | Hệ thống Cảnh báo Rủi ro Hệ thống — PCA trên VN30, phát hiện SAFE/WARNING/CRITICAL |
| 6 | **Dispersion** | Phân tích phân tán thị trường — Volatility skew, term structure |
| 7 | **VaRES Engine** | 3 Module: A-Single Ticker, B-VN30 Stress, C-Market Complacency với Self-Baseline |
| 8 | **Manipulation Detection** | Phát hiện dấu hiệu thao túng giá — Các metrics đặc biệt về hành vi giao dịch |
| 9 | **Var-CVaR VNINDEX** | Value-at-Risk & Expected Shortfall cho VNINDEX — Rolling σ, Parametric & Historical VaR, ES |
| 10 | **History Score & Regime** | Backtest scoring system cho các regime thị trường |
| 11 | **Backtest Strategy** | Framework backtest chiến lược giao dịch |

---

## 🤖 AI CIO Report — Báo cáo Tổng hợp AI

| Tính năng | Mô tả |
|-----------|-------|
| **Multi-Provider Support** | Kimi 2.6, DeepSeek V4 Pro — Chọn trực tiếp trên UI |
| **Executive Summary** | Tạo báo cáo tổng hợp tự động từ dữ liệu market + macro + behavioral |
| **PDF Export** | Xuất báo cáo PDF với font Unicode (DejaVu) |
| **GitHub Sync** | Đồng bộ cache AI report lên GitHub để lưu trữ lịch sử |
| **API Key Shortcut** | Nhập API key trực tiếp hoặc dùng shortcut 4 số từ Secrets |

---

## 📁 Cấu trúc thư mục

```
/workspace/
├── app.py                        # Trang chủ — Điều hướng 3 nhánh chính
├── config.py                     # Cấu hình toàn cục, AI provider map
├── requirements.txt              # Dependencies
├── tickers.csv                   # Danh sách mã cổ phiếu
├── pages/                        # 3 trang nhánh phân tích
│   ├── A_Macro_Analysis.py       # Macro Analysis hub
│   ├── B_Micro_Analysis.py       # Micro Analysis hub
│   ├── C_Behavioral_Finance.py   # Behavioral Finance hub
│   └── tools_page_*/             # Sub-pages (history score, backtest)
├── tools/                        # 19 tool modules
│   ├── fed_liquidity/
│   ├── global_financial_conditions/
│   ├── vnibor/
│   ├── ltmm/
│   ├── vn100_earnings_health/
│   ├── pairs_trading/
│   ├── factor_examination/
│   ├── fear_greed/
│   ├── upside_ratio/
│   ├── risk_adjusted_growth/
│   ├── market_breadth/
│   ├── esr_monitor/
│   ├── dispersion/
│   ├── va_res/
│   ├── manipulation/
│   ├── var_cvar_vnindex/
│   └── backtest/
├── command/                      # Scripts cập nhật dữ liệu & báo cáo
│   ├── update_data.py
│   ├── update_fed_liquidity.py
│   ├── update_global_financial_conditions.py
│   ├── update_vnibor.py
│   ├── update_sector_data.py
│   ├── update_bank_fundamentals.py
│   ├── update_factor_examination.py
│   ├── run_ai_cio_auto.py
│   └── generate_report.py
├── shared/                       # Module dùng chung
│   ├── page_layout.py
│   ├── data_loader.py
│   ├── ai_cio.py
│   ├── api_key_helper.py
│   ├── github_sync.py
│   └── daily_cache.py
├── data_lake/                    # Dữ liệu thị trường (CSV)
│   ├── market_data.csv
│   ├── market_volume.csv
│   ├── vnindex_cache.csv
│   ├── vn30_cache.csv
│   ├── fed_liquidity_cache.csv
│   ├── global_financial_conditions_cache.csv
│   ├── bank_fundamentals.csv
│   ├── daily_cache/              # Cache AI reports
│   └── vn100_earnings_health/
├── reports/                      # Báo cáo PDF xuất ra
├── promt/                        # Prompt templates cho AI (15+ files)
├── fonts/                        # Font DejaVu cho PDF
└── docs/                         # Documentation handbooks
    ├── GFCM-handbook.md
    ├── factor_examination_handbook.md
    ├── pairs_trading_handbook.md
    └── vn100_earnings_health_handbook.txt
```

---

## 🛠️ Cài đặt Local

### 1. Clone repository

```bash
git clone https://github.com/<your-username>/onl_quant_platform.git
cd onl_quant_platform
```

### 2. Tạo môi trường ảo

```bash
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows
```

### 3. Cài dependencies

```bash
pip install -r requirements.txt
```

### 4. Cấu hình biến môi trường

Tạo file `.env` ở thư mục gốc:

```bash
VNSTOCK_API_KEY="your_vnstock_api_key"
FRED_API_KEY="your_fred_api_key"       # Tùy chọn: cho Fed Liquidity data
GITHUB_TOKEN="your_github_token"       # Tùy chọn: cho GitHub Sync feature
```

> ⚠️ **Lưu ý**: File `.env` đã được thêm vào `.gitignore`, đảm bảo không bị commit lên GitHub.
> 
> **API Keys cho AI CIO**: Kimi AI hoặc DeepSeek API Key không cần đặt trong `.env` — người dùng sẽ nhập trực tiếp trên giao diện Streamlit (hoặc dùng shortcut 4 số từ Secrets).

### 5. Cập nhật dữ liệu

```bash
# Cập nhật toàn bộ dữ liệu thị trường
python command/update_data.py

# Hoặc cập nhật từng module riêng lẻ:
python command/update_fed_liquidity.py
python command/update_global_financial_conditions.py
python command/update_vnibor.py
python command/update_sector_data.py
python command/update_bank_fundamentals.py
python command/update_factor_examination.py
```

### 6. Chạy ứng dụng

```bash
streamlit run app.py
```

Ứng dụng sẽ mở tại `http://localhost:8501`

---

## ☁️ Deploy lên Streamlit Cloud

### Bước 1: Push lên GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```

> **Lưu ý quan trọng**: Đảm bảo `.env` không được push lên GitHub. File này đã có trong `.gitignore`.

### Bước 2: Kết nối Streamlit Cloud

1. Truy cập [share.streamlit.io](https://share.streamlit.io)
2. Đăng nhập bằng GitHub
3. Click **"New app"** → Chọn repository của bạn
4. File chính: `app.py`

### Bước 3: Cấu hình Secrets

Trong Streamlit Cloud, vào **Settings → Secrets**, thêm:

```toml
VNSTOCK_API_KEY = "your_vnstock_api_key"
FRED_API_KEY = "your_fred_api_key"              # Tùy chọn: cho Fed Liquidity data
GITHUB_TOKEN = "your_github_token"              # Tùy chọn: cho GitHub Sync feature

# Optional: API key shortcuts (4 số) cho AI CIO
# Người dùng có thể gõ shortcut thay vì paste full API key
AI_KIMI_SHORTCUT = "1234"
AI_DEEPSEEK_SHORTCUT = "5678"
```

> **Lưu ý**: 
> - Kimi/DeepSeek API Key không bắt buộc trong Secrets vì người dùng nhập trực tiếp trên UI.
> - Tuy nhiên, bạn có thể lưu API keys dưới dạng shortcut (4 số) để tiện sử dụng.
> - Nếu muốn set default model, thêm `AI_MODEL` và `AI_TEMPERATURE`.

### Bước 4: Khởi động lại app

Click **"Reboot"** để áp dụng secrets.

---

## 🔄 Cập nhật dữ liệu thị trường

Dữ liệu không tự động cập nhật trên Streamlit Cloud. Bạn có thể:

- **Cách 1**: Chạy `python command/update_data.py` trên local → push `data_lake/*.csv` lên GitHub
- **Cách 2**: Tự động hóa với GitHub Actions (khuyến nghị cho production)
- **Cách 3**: Thêm chức năng "Update Data" vào app (cần xử lý rate limit API và thời gian chạy ~5 phút)

### Scripts cập nhật riêng lẻ

| Script | Mô tả |
|--------|-------|
| `update_data.py` | Cập nhật toàn bộ market data, VNINDEX, VN30 |
| `update_fed_liquidity.py` | Cập nhật Fed Liquidity từ FRED API |
| `update_global_financial_conditions.py` | Cập nhật VIX, MOVE, HY OAS, CCC OAS |
| `update_vnibor.py` | Cập nhật lãi suất liên ngân hàng VNIBOR |
| `update_sector_data.py` | Cập nhật dữ liệu sector |
| `update_bank_fundamentals.py` | Cập nhật fundamentals ngân hàng |
| `update_factor_examination.py` | Cập nhật factor scores cho 400 tickers |
| `run_ai_cio_auto.py` | Chạy tự động tạo AI CIO Executive Summary |

---

## 🧰 Dependencies chính

| Package | Mục đích |
|---------|----------|
| `streamlit` | Web UI framework |
| `pandas` / `numpy` | Xử lý dữ liệu |
| `plotly` | Biểu đồ tương tác |
| `polars` | Xử lý dữ liệu hiệu năng cao |
| `vnstock` | Dữ liệu chứng khoán VN |
| `fredapi` | Dữ liệu kinh tế Mỹ từ FRED |
| `yfinance` | Dữ liệu tài chính toàn cầu |
| `openai` | Tích hợp AI CIO (compatible với Kimi/DeepSeek) |
| `fpdf2` | Xuất báo cáo PDF |
| `arch` | Mô hình EGARCH, volatility |
| `scikit-learn` | Machine learning (PCA, regression) |
| `statsmodels` | Cointegration, OLS, time series |
| `hmmlearn` | Hidden Markov Models |
| `numba` | JIT compilation cho tính toán nặng |
| `scipy` | Thống kê và tối ưu hóa |

---

## ⚠️ Lưu ý quan trọng

- **Dữ liệu thị trường** trong `data_lake/` được push lên GitHub để app chạy ngay trên Streamlit Cloud. Bạn nên cập nhật thường xuyên (hàng ngày/tuần).
- **API Keys**:
  - `VNSTOCK_API_KEY`: Bắt buộc cho cập nhật dữ liệu VNStock
  - `FRED_API_KEY`: Tùy chọn, cho Fed Liquidity data
  - `GITHUB_TOKEN`: Tùy chọn, cho GitHub Sync feature
  - **AI API Keys** (Kimi/DeepSeek): Nhập trực tiếp trên UI hoặc lưu shortcut trong Secrets
- **Cache**: Các file cache (`.pkl`, `daily_cache/`) đã được loại bỏ khỏi Git để giữ repo gọn nhẹ, nhưng được sinh tự động khi chạy app.
- **Font PDF**: Font DejaVuSans đã được include trong `/fonts/` để hỗ trợ xuất PDF tiếng Việt.

---

## 📚 Documentation Handbooks

Dự án bao gồm các tài liệu hướng dẫn chi tiết:

| Handbook | Nội dung |
|----------|----------|
| `docs/GFCM-handbook.md` | Global Financial Conditions Monitor |
| `docs/factor_examination_handbook.md` | Portfolio Factor Examination methodology |
| `docs/pairs_trading_handbook.md` | Pairs Trading Research Lab guide |
| `docs/vn100_earnings_health_handbook.txt` | VN100 Earnings Health framework |
| `docs/backtest_proposal.md` | Backtest strategy proposal |

---

## 📄 License

Dự án sử dụng cho mục đích nghiên cứu & phân tích cá nhân.
