# Quant Platform — Manual Handbook

**Phiên bản:** 2026-05-19
**Đối tượng:** Retail trader VN, đọc kết quả **thủ công** trước khi tích hợp AI CIO.
**Mục tiêu:** Setup nền tảng + đọc hiểu output từng tool + framework kết hợp signal khi chưa kích hoạt synthesis AI.

---

## Mục lục

1. [Setup nhanh](#1-setup-nhanh)
2. [Cập nhật dữ liệu](#2-cập-nhật-dữ-liệu)
3. [Cấu hình AI key (optional)](#3-cấu-hình-ai-key-optional)
4. [Tổng quan 3 nhánh phân tích](#4-tổng-quan-3-nhánh-phân-tích)
5. [Đọc hiểu kết quả 11 tool](#5-đọc-hiểu-kết-quả-11-tool)
6. [Framework kết hợp signal khi CHƯA có AI CIO](#6-framework-kết-hợp-signal-khi-chưa-có-ai-cio)
7. [Cạm bẫy thường gặp](#7-cạm-bẫy-thường-gặp)
8. [FAQ vận hành](#8-faq-vận-hành)

---

## 1. Setup nhanh

### 1.1. Yêu cầu

- Python **3.10 – 3.11** (production). Python 3.12+ có thể chạy nhưng `numba` / `polars` đôi khi cần stub.
- `pip install -r requirements.txt`
- Linux/macOS/Windows đều OK.

### 1.2. Chạy local

```bash
streamlit run app.py
```

Mặc định mở `http://localhost:8501`. Sidebar bên trái = chọn page (A_Macro / B_Micro / C_Behavioral) hoặc chọn từ 3 thẻ trên home.

### 1.3. Chạy trên Streamlit Cloud

- Repository deploy từ branch `main`.
- Cần `GITHUB_TOKEN` + (optional) `AI_KEY_*` trong **Secrets** của Cloud Dashboard.
- Mỗi push lên `main` → Cloud auto-rebuild (~2 phút).

---

## 2. Cập nhật dữ liệu

Toàn bộ tool đọc CSV từ `data_lake/`. App **không** gọi API trực tiếp — luôn đọc cache đã lưu.

### 2.1. Daily update (giá + volume cho ~250 mã)

```bash
python command/update_data.py
```

Smart-incremental: chỉ fetch ngày thiếu, ghi đè bằng `combine_first`. Thời gian ~5 phút.

### 2.2. Backfill khi đổi schema (vd. thêm field volume)

```bash
python command/update_data.py --backfill 2190   # 6 năm
```

### 2.3. Fundamentals + Macro

| Loại dữ liệu | Lệnh | Tần suất |
|---|---|---|
| Bank fundamentals (BCTC quý) | `python command/update_bank_fundamentals.py` | Quý |
| Fed Liquidity (WALCL/TGA/RRP) | `python command/update_fed_liquidity.py` | Thứ Tư hàng tuần |
| Sector map (ICB) | `python command/update_sector_data.py` | Khi listing mới |

### 2.4. Trên Cloud (GitHub Actions tự chạy)

- `update_pipeline.yml` — chạy lúc **14:30 VN** mỗi phiên giao dịch.
- `fed_liquidity_weekly.yml` — Thứ Tư.
- `ai_cio_daily.yml` — **14:45 VN**, tạo executive summary tự động.

Nếu bạn thấy banner "✅ Data lake sẵn sàng — cập nhật lần cuối: 19/05/2026 14:32" ở trang chủ → data đã fresh.

---

## 3. Cấu hình AI key (optional)

Nếu **không** dùng AI CIO, bạn có thể bỏ qua mục này — toàn bộ chart & metric vẫn render bình thường, chỉ thiếu "executive summary" tổng hợp.

### 3.1. Provider hỗ trợ

| Provider | Model | Base URL | Đăng ký |
|---|---|---|---|
| Kimi (Moonshot) | `kimi-k2.6` | `https://api.moonshot.ai/v1` | platform.moonshot.ai |
| DeepSeek | `deepseek-chat` (V4 Pro) | `https://api.deepseek.com/v1` | platform.deepseek.com |

### 3.2. Cách lưu key

**Local**: tạo `.env` (chưa commit):
```
OPENAI_API_KEY=sk-xxxxx
```

**Streamlit Cloud**: vào *Settings → Secrets*, paste:
```toml
AI_KEY_1234 = "sk-xxxxx"
GITHUB_TOKEN = "ghp_xxxxx"
```

Trên UI: gõ `1234` vào ô shortcut → app tra `AI_KEY_1234` từ Secrets. Tránh paste key thật lên UI.

---

## 4. Tổng quan 3 nhánh phân tích

| Nhánh | Trang | Mục tiêu | Chu kỳ check |
|---|---|---|---|
| **A. Macro** | `A_Macro_Analysis` | Thanh khoản hệ thống toàn cầu (Fed) → flow tiền vào EM | Tuần |
| **B. Micro** | `B_Micro_Analysis` | Cấu trúc giữa các mã (cointegration, pair trading) | Phiên |
| **C. Behavioral** | `C_Behavioral_Finance` | Tâm lý đám đông + regime VNINDEX | Phiên |

**Luồng đọc đề xuất**: A → C → B.
- A trả lời "Liquidity environment đang ADD/HOLD/CUT?"
- C trả lời "Đám đông đang ở Fear/Neutral/Greed? Volatility regime gì? Risk tail thế nào?"
- B trả lời "Có pair edge nào tactical không?"

---

## 5. Đọc hiểu kết quả 11 tool

### 5.1. Fed Liquidity (Macro)

**Công thức**: `Net Liquidity = WALCL − TGA − RRP`. Z-score 52 tuần.

| Trạng thái | Z-score 52W | Hành động |
|---|---|---|
| **ADD** | > +1.0 | Liquidity dồi dào → risk-on, ưu tiên cổ phiếu beta cao |
| **HOLD** | −1.0 → +1.0 | Trung tính |
| **CUT** | < −1.0 | Liquidity rút → giảm position, ưu tiên defensive |

⚠️ Lag 1-2 tuần (Fed publish thứ Năm). Đừng dùng cho timing intra-week.

### 5.2. Fear & Greed (Behavioral)

**Composite 0-100** từ PCA của: momentum, volatility, breadth, put/call proxy, junk bond proxy.

| Vùng | Score | Ý nghĩa |
|---|---|---|
| Extreme Fear | 0-25 | Đám đông panic → contrarian long |
| Fear | 25-45 | Cẩn trọng |
| Neutral | 45-55 | Không edge từ tâm lý |
| Greed | 55-75 | Caution, không margin |
| **Extreme Greed** | 75-100 | **Bull top trap pattern — KHÔNG margin kể cả vol thấp** |

🔥 **Anti-pattern đã học**: Score > 80 + vol thấp = setup cho distribution, KHÔNG phải tín hiệu long thêm.

### 5.3. Upside / Downside Ratio

Monte Carlo 5000 sims (Hybrid Logit-AR + Beta-AR) → xác suất `ret > +X%` vs `ret < −X%` trong N phiên tới.

**Đọc**:
- Ratio > 2.0 → asymmetric upside, risk/reward tốt
- Ratio 0.5 - 2.0 → symmetric, không edge
- Ratio < 0.5 → downside thiên lệch, hedge / giảm size

### 5.4. Risk-Adjusted Growth

**Disciplined Return** = `CAGR × (1 − DD_max)`. Bonus cho ngân hàng: **Economic Alpha** = `ROE − COE`.

Sort cổ phiếu theo DR. **KHÔNG** chọn top theo CAGR đơn (CAGR cao thường đi kèm DD lớn = stress khi sideways).

### 5.5. Market Breadth

% cổ phiếu trên MA20 / 60 / 125 / 252.

| Signal | Đọc |
|---|---|
| %MA20 > 70%, %MA252 > 60% | Uptrend mạnh, broad-based |
| %MA20 > 70%, %MA252 < 40% | Bear market rally — KHÔNG bền |
| %MA20 < 30%, %MA252 < 30% | Capitulation — watch reversal |
| Divergence: VNINDEX up, %MA20 down | **Distribution top** — cảnh báo |

### 5.6. ESR Monitor (Equity Stress Regime)

5 pillar SSI: **S_VOL, S_PRES, S_COR, S_LIQ (Volume Dry-Up), S_VAL** → PCA(1) → HMM 4 state.

| State | Tên | Action |
|---|---|---|
| 0 | Calm Bull | Long, leverage được |
| 1 | Choppy Neutral | Trim, không add |
| 2 | Stress Build | Hedge, giảm beta |
| 3 | Crisis | Cash 50%+, defensive only |

**S_LIQ = Volume Dry-Up** quan trọng nhất với VN: log ratio MA20/MA252 dollar volume. Dry-up trước crash 2-3 tuần.

### 5.7. Dispersion

**CSAD** = mean(|r_i − r_market|). **DPI** = dispersion percentile index.

| DPI | Ý nghĩa |
|---|---|
| > 80 | High dispersion → stock-picking edge, pair trade hiệu quả |
| 40-60 | Trung bình |
| < 20 | Low dispersion (đồng pha) → systematic risk, đa dạng hoá vô hiệu |

### 5.8. Manipulation

PCA composite từ VIC/VHM/VRE so với VN30F1M, 5 regime event study. Phát hiện divergence bất thường giữa VinGroup và phái sinh — chỉ báo bị thao túng ngắn hạn.

**Đọc nhanh**: percentile > 90 = đang bị kéo bất thường, fade signal (không chase).

### 5.9. VaRES (VaR + Expected Shortfall)

Cornish-Fisher VaR/ES + **Module C: Complacency** (self-baseline).

| Output | Đọc |
|---|---|
| VaR 95% 1d | Mức lỗ tối đa dự kiến trong 1 phiên với 95% confidence |
| ES (CVaR) 95% | Lỗ trung bình **nếu** breach VaR |
| Complacency score > 80 | Vol implied < vol thực — **stress sắp đến** |

### 5.10. VaR-CVaR VNINDEX (EVT)

Gaussian + Historical + **EVT POT-GPD** (95/99/99.5%) + Hill index.

**Khi nào tin EVT > Gaussian**: khi Hill index < 4 (tail dày, fat-tail) — Gaussian sẽ **under-estimate** tail risk. Lúc đó dùng EVT POT-GPD 99.5% làm budget rủi ro.

### 5.11. Pairs Trading Research Lab (Micro) — **NEW**

5 tab:

**Tab 1 — Cluster Scan**: Chọn 1 trong 7 cluster predefined (Vingroup / Big4_Bank / Steel / Securities / Private_Bank / Oil_Gas / Utility). Johansen test → `n_coint_vectors`. Nếu = 0 → cluster không cointegrated 95% CI, **không trade**.

**Tab 2 — Pairwise Heatmap**: Heatmap p-value Engle-Granger toàn cluster. Ô **đỏ** (p<0.05) = cointegrated. Tìm 2-3 pair đỏ đậm nhất để focus.

**Tab 3 — Custom Pair**: Pick 2 mã bất kỳ. Output:
- `β` (hedge ratio) — số CP mã 2 cần short cho mỗi CP mã 1 long
- `half-life` (OU) — số phiên dự kiến để spread về mean. **Filter band 5-30 ngày** (ngoài range = không trade)
- `Hurst` < 0.5 → confirm mean-reverting
- Z-score 60d — entry signal

**Tab 4 — Aggregate Backtest**: P&L portfolio đa pair sau cost 15bps.

**Tab 5 — Live Signals**: Bảng pair cointegrated × current z. **Action rule**:
- |z| > 2 → entry
- |z| > 3 → stop, quarantine 60 phiên
- Time stop = 2 × half-life

⚠️ **Cảnh báo**:
- **Vingroup cluster** không pass Johansen 95% (VRE thuần retail mall vs VIC/VHM RE) — **risk cao**.
- Corp-action (split/dividend) có thể fake-break cointegration.
- VN lunch break 11:30-13:00 ICT → order queue, không execute.
- FOL: app assume foreign_room > 5%, verify manually trước khi đặt lệnh.

---

## 6. Framework kết hợp signal khi CHƯA có AI CIO

Khi chưa có AI CIO synthesis, đọc thủ công theo **3 layer**:

### Layer 1 — Liquidity gate (binary)

> **Fed Liquidity = CUT?** → giảm gross exposure xuống ≤50% NAV, bỏ qua layer 2-3.

Nếu HOLD hoặc ADD → tiếp tục.

### Layer 2 — Regime gate (binary)

> **ESR HMM State = 2 (Stress Build) hoặc 3 (Crisis)?** → defensive only.

Nếu State 0 hoặc 1 → tiếp tục.

### Layer 3 — Sentiment + execution

| Combo | Action gợi ý |
|---|---|
| Fear < 35 + Breadth %MA252 < 40 | Bottom fishing — buy quality (RAG top quintile) |
| Greed > 75 + Complacency > 80 | **Distribute**, hedge bằng VN30F |
| DPI > 80 + Pairs cointegrated abundant | Tactical pair trade, market-neutral |
| Manipulation percentile > 90 | Fade VIC/VHM/VRE move, không chase |
| Fear & Greed neutral + DPI low | **No-trade zone**, giữ cash |

### Decision matrix tóm tắt

```
                  ┌─ Fed CUT ───────────→ 50% cash, defensive
                  │
Liquidity? ───────┤
                  │                    ┌─ ESR 2/3 ──→ hedge / trim
                  │                    │
                  └─ Fed HOLD/ADD ─────┤
                                       │              ┌─ F&G < 35 → long quality
                                       └─ ESR 0/1 ───┤
                                                      ├─ F&G 35-75 → status quo / pair trade
                                                      └─ F&G > 75 → distribute / hedge
```

---

## 7. Cạm bẫy thường gặp

1. **Margin khi F&G > 80, vol thấp** → bull top trap. KHÔNG margin dù backtest đẹp.
2. **Dùng giá tuyệt đối trong report cũ** → training data 2-3 năm lag; luôn cross-check giá hiện tại.
3. **Amihud illiquidity cho VN30** → không correlate stress. Dùng Volume Dry-Up (đã built-in S_LIQ).
4. **Cache stale** sau khi đổi methodology → bump `s_<feature>_method: "vN"` trong cache key (dev-side).
5. **Timezone bug**: cache key dùng `date.today()` (UTC trên Cloud, UTC+7 local) → có thể lệch ngày. Đang chuyển sang `df.index[-1]`.
6. **Survivorship** ở Pairs Trading: cluster predefined chỉ gồm mã còn list — không backtest "what-if delisted".
7. **EVT POT-GPD** cần ≥ 500 obs sample, KHÔNG dùng với rolling 60d.

---

## 8. FAQ vận hành

**Q: Data chưa update hôm nay, có chạy được không?**
A: Được — app sẽ dùng cache T-1. Banner trên home báo "cập nhật lần cuối: ...".

**Q: Streamlit Cloud không thấy tool mới tôi vừa push?**
A: Cloud chỉ deploy từ branch `main`. Nếu code ở feature branch → cần merge PR vào main (hoặc đổi deploy target).

**Q: AI CIO crash với lỗi `OPENAI_API_KEY missing`?**
A: Vào Streamlit Secrets, paste `AI_KEY_<4digit>` → trên UI gõ 4 digit đó. Hoặc paste trực tiếp `OPENAI_API_KEY = "sk-..."`.

**Q: Tôi muốn thêm tool mới?**
A: Theo skeleton `tools/<name>/{quant,ui}/__init__.py + page.py`. Đăng ký vào `pages/<X>_Branch>.py:TOOLS`. Chi tiết: `docs/skill.md` §6.

**Q: Backtest pipeline tách bạch khỏi live?**
A: Có. ESR Monitor live dùng `PRODUCTION_REGIME_METHOD = 'hmm'`, backtest dùng `'hmm_walk_forward'` để look-ahead-free. Xem `tools/esr_monitor/quant/metrics.py:51`.

**Q: Làm sao tin một pair backtest có Sharpe 1.5?**
A: Check (1) cost 15bps đã include, (2) half-life trong 5-30d, (3) Hurst < 0.5, (4) ADF p < 0.05, (5) backtest qua ≥ 2 năm và ≥ 2 regime khác nhau. Nếu chỉ pass 1 regime → over-fit.

---

**Liên hệ / Issue**: tạo issue trên GitHub repo `cuocsongthinhvuong8868-sketch/onl_quant-platform`.

**Tài liệu kỹ thuật sâu hơn**: `docs/skill.md` (session log toàn bộ build).
