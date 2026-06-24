# GFCM Handbook — Global Financial Conditions Monitor

**Version**: 2026-05-20
**Tool path**: `tools/global_financial_conditions/`
**Page**: A_Macro_Analysis → "Global Financial Conditions Monitor"

---

## 1. Mục tiêu

GFCM tổng hợp **11 chỉ báo cross-asset** (3 nhóm: volatility, credit, macro overlay) thành 1 dashboard duy nhất + 1 composite stress index (PC1) + classification (Regime + Driver). Trả lời 1 câu hỏi:

> *"Global financial conditions hiện tại có tight không, và stress đến từ đâu?"*

Sau đó dùng signal này để đánh giá spillover sang VN-Index với lag 4-8 tuần (chỉ là context — KHÔNG đưa khuyến nghị tỷ trọng VN cụ thể vì đó là job của AI CIO synthesis).

---

## 2. 11 Indicators

### Nhóm Volatility (5)

| Indicator | Source | Đo | Tăng = |
|---|---|---|---|
| **VIX** | FRED `VIXCLS` | SPX 30d implied vol | Equity risk-off US |
| **MOVE** | Yahoo `^MOVE` | Treasury implied vol | Rates uncertainty / Fed pivot fear |
| **SKEW** | Yahoo `^SKEW` | Tail risk premium (OTM put pricing) | Hidden left-tail fear, black-swan hedging |
| **OVX** | Yahoo `^OVX` | Oil ETF vol | Energy / geopolitical shock (Middle East, OPEC) |
| **VVIX** | Yahoo `^VVIX` | Vol-of-vol | Derivatives market stress, early warning |

### Nhóm Credit (4)

| Indicator | Source | Đo | Tăng = |
|---|---|---|---|
| **HY OAS** | FRED `BAMLH0A0HYM2` | US HY broad spread | Broad credit risk (default + liquidity) |
| **CCC OAS** | FRED `BAMLH0A3HYC` | Deep junk spread | Default-cycle fear (late-cycle) |
| **IG OAS** | FRED `BAMLC0A0CM` | US Investment Grade spread | Flight-to-quality stress; quality re-pricing |
| **EM OAS** | FRED `BAMLEMCBPIOAS` | EM Corp Plus spread | EM stress contagion, FX-linked credit |

### Nhóm Macro Overlay (2)

| Indicator | Source | Đo | Tăng/Giảm = |
|---|---|---|---|
| **2s10s** | FRED `T10Y2Y` | 10Y − 2Y UST yield | Âm (inverted) → recession trong 12-18 tháng |
| **DXY** | Yahoo `DX-Y.NYB` | Trade-weighted USD strength | DXY ↑ → EM FX pressure, FDI outflow |

### Derived
- **Credit Quality Spread (CQS) = CCC − HY** — dispersion trong credit quality. CQS widens > HY widens ⇒ deterioration concentrated ở junk tier.

---

## 3. Pipeline & PCA Logic

```
Raw 11 series
    ↓
Per-series z-score (rolling 252d) + Percentile rank (rolling 252d)
    ↓
PCA fit static trên 6 core series (VIX, MOVE, SKEW, HY, CCC, IG)
    → PC1 (common stress factor), PC2 (divergence)
    ↓
PC1_smooth = PC1.ewm(span=5)  ← EMA(5) giảm regime flicker
    ↓
PC1_pct = rolling percentile rank 252d của PC1_smooth
    ↓
Regime: PC1_pct ≥ 80% = STRESS · 50-80% = ELEVATED · < 50% = CALM
Driver: argmax percentile của 6 core series (+ BROAD_STRESS nếu ≥ 4/6 ≥ 80%)
```

### Tại sao chỉ 6 series vào PCA?
PC1 cần "core stress" sạch và đối xứng (3 vol + 3 credit). 5 series còn lại (OVX, VVIX, EM, 2s10s, DXY) là **auxiliary** — chỉ z + percentile, đọc thủ công trên dashboard và trong AI prompt. Lý do:
- **OVX, VVIX**: niche shock (oil-specific, derivatives-specific) — dilute PC1 nếu đưa vào
- **EM OAS**: EM-specific, không phải global stress chung
- **2s10s, DXY**: macro overlay, có cycle riêng (DXY mean-revert, 2s10s leading recession), không phải stress indicator

### Sign convention PCA
- PC1 anchor: VIX_z loading dương → PC1 cao = stress (không phải đảo dấu)
- PC2 anchor: HY_z loading dương → PC2 cao = credit-tilt, PC2 thấp = vol-tilt

### Tại sao EMA(5) cho PC1?
Raw PC1 có high-freq noise → regime bands (STRESS/ELEVATED/CALM) nhảy nhanh trong vài ngày, tạo false signal. EMA span=5 (half-life ~3 ngày, lag ~3 ngày) làm signal sạch hơn. Pattern theo **Goldman GSFCI** và **Chicago Fed NFCI**. PC1 raw vẫn được giữ để tính 5d change (đo momentum).

---

## 4. Cách đọc Regime label — IMPORTANT

### Regime KHÔNG dùng PC1_smooth value, mà dùng PC1_pct (percentile rank)

| Threshold | Regime | Ý nghĩa |
|---|---|---|
| PC1_pct ≥ 80% | **STRESS** 🔴 | PC1 đang ở top 20% của 1 năm gần nhất |
| 50% ≤ PC1_pct < 80% | **ELEVATED** 🟠 | Trên trung vị 1Y nhưng chưa critical |
| PC1_pct < 50% | **CALM** 🟢 | Dưới trung vị 1Y |

### Tại sao cùng 1 giá trị PC1 có thể có Regime khác?

**Case study thực tế từ session 2026-05-20**:
- Ngày 3/3/2026: `PC1_smooth = 0.89σ` → ELEVATED
- Ngày 20/5/2026: `PC1_smooth = 0.82σ` → STRESS

→ Tưởng ngược nhau (0.89 > 0.82 mà lại ELEVATED?), nhưng KHÔNG inconsistent:

| Date | Rolling 252d window chứa | PC1_pct | Regime |
|---|---|---|---|
| 3/3/2026 | Có spike May 2025 ~6σ | ~60-70% | ELEVATED |
| 20/5/2026 | Spike May 2025 đã rời window; April 2026 spike vẫn còn nhưng distribution dịch xuống | ~85% | STRESS |

**Cơ chế**: cùng PC1 value, nhưng vì window 252d gần nhất thay đổi (bao gồm các giá trị khác nhau), nên **percentile rank** khác nhau. Đây là feature, không phải bug — regime đo "stress hiện tại so với 1 năm gần nhất", không phải so với toàn bộ history.

→ Logic này tương tự cách Chicago Fed NFCI dùng deviation relative-to-recent thay vì absolute threshold.

### Đường y=0 trên chart PC1
Đó **không phải threshold critical**, chỉ là **PCA long-term mean** (PCA tự center). PC1 > 0 = above long-term average stress; thông tin reference, không define regime.

---

## 5. Driver Flag

Sau khi xác định Regime, Driver chỉ ra **stress đến từ đâu** trong 6 core series:

| Driver | Trigger | Ý nghĩa |
|---|---|---|
| `EQUITY_DRIVEN` | VIX_pct cao nhất | Fear concentrated ở equity (earnings, geopolitics, idiosyncratic) |
| `RATES_DRIVEN` | MOVE_pct cao nhất | Fear ở Fed path / Treasury supply / duration risk |
| `SKEW_DRIVEN` | SKEW_pct cao nhất | Hidden tail fear, smart money hedging bất chấp VIX bình thường |
| `HY_CREDIT_DRIVEN` | HY_pct cao nhất | Broad credit repricing, liquidity squeeze |
| `CCC_CREDIT_DRIVEN` | CCC_pct cao nhất | Default fear deep junk (late-cycle) |
| `IG_CREDIT_DRIVEN` | IG_pct cao nhất | Flight-to-quality break-down, systemic concern |
| `BROAD_STRESS` | ≥ 4/6 series ≥ 80% percentile | Systemic risk-off, không concentrate ở 1 driver |
| `NO_STRESS` | 0/6 series ≥ 80% | Benign FCI |

---

## 6. Spillover to VN-Index (lag 4-8 tuần)

| Indicator ↑ | Cơ chế → VN |
|---|---|
| VIX ↑ | Global risk-off → foreign sell VN → -correlation |
| MOVE ↑ | DXY ↑ → EM FX pressure → FDI outflow |
| SKEW ↑ | Hidden tail fear → risk-parity unwinding lan EM |
| OVX ↑ | Oil shock → CPI VN ↑ → SBV thắt; VN net importer dầu, -beta |
| VVIX ↑ | Derivatives stress → liquidity withdrawal toàn cầu |
| HY OAS ↑ | Risk premium toàn cầu ↑ → discount rate VN equity ↑ |
| CCC OAS ↑ | Carry trade unwind → EM stress contagion |
| IG OAS ↑ | Quality flight → EM bond outflow → FX pressure |
| EM OAS ↑ | EM credit stress direct → VN sovereign/corp re-rating |
| CQS widens | Late-cycle warning → defensive positioning bias EM |
| 2s10s inverted hoặc steepening từ âm | Recession risk US → demand shock EM exports |
| DXY ↑ | VND pressure, FDI outflow, VN-Index headwind cứng |

---

## 7. Cách đọc Dashboard

### Tab 1 — Level
3 sub-grids hiển thị raw value 11 indicators:
- **Volatility (5)**: VIX/MOVE/SKEW/OVX/VVIX với mean line lịch sử
- **Credit (4)**: HY/CCC/IG/EM OAS
- **Macro (2)**: 2s10s curve, DXY

**Use case**: thấy nhanh từng indicator đang ở đâu so với mean lịch sử của chính nó.

### Tab 2 — Analytics
- **Header metrics**: Regime icon + Driver + PC1 EMA(5) value + PC1 5d delta
- **6 PCA core percentiles** + **5 auxiliary percentiles** ở 2 hàng
- **Chart PC1 + Regime bands**: 2 line — raw mờ (gray) + EMA(5) bold (dark), background color = regime
- **Percentile grid 6 panel**: hiển thị PR 1Y của 6 PCA core với 80% threshold shaded
- **Scatter PC1 vs PC2**: 252 phiên gần nhất, color = recency
- **Credit Quality Spread**: line CCC − HY với percentile annotation
- **AI Analysis tab**: prompt 8 sections, output 550-700 từ tiếng Việt + JSON tail

---

## 8. Limitations & Caveats

1. **ICE BofA truncation**: 4 series FRED (HY/CCC/IG/EM) chỉ có history ~3 năm do ICE pull license 2021. Đây là lý do rolling window đặt 252d (1Y) thay vì 756d (3Y) — để có đủ valid regime points.
2. **MOVE Yahoo coverage** bắt đầu ~2003 — không backtest pre-2003.
3. **PC1 5d change dùng raw**, không phải smoothed → có thể spike đột biến trong khi Regime chưa kịp chuyển (early warning hữu ích).
4. **EMA(5) lag**: regime trigger lag ~3 ngày so với raw — chấp nhận được vì avoid noise-driven false transitions.
5. **PCA point-in-time**: expanding-window, refit mỗi 21 phiên và chỉ dùng dữ liệu trước ngày dự báo. Historical PC1/PC2 không bị revision khi append dữ liệu tương lai; loadings vẫn có thể thay đổi theo từng refit và cần theo dõi stability.
6. **VN spillover lag 4-8 tuần là empirical**, không phải hard rule. Khi crisis lớn (LTCM 1998, GFC 2008, COVID 2020), lag có thể ngắn xuống còn 1-2 tuần.
7. **AI prompt KHÔNG inject vào executive summary aggregator** (`shared/ai_cio.py`) — GFCM là macro tool đứng riêng, theo precedent Fed Liquidity.

---

## 9. Operational

### Update cache
```bash
# Cần FRED_API_KEY trong .env hoặc env var
python command/update_global_financial_conditions.py
```

### Auto-update cron
GitHub Actions workflow `.github/workflows/gfcm_daily.yml` chạy lúc:
- **22:00 UTC Mon-Fri** = 05:00 VN sáng Thứ 3-Thứ 7
- Sau US market close (~21:00 UTC) + FRED OAS publish T+1
- Cần secret `FRED_API_KEY`

### Probe FRED IDs (debug)
```bash
python command/probe_fred_series.py
```

### File outputs
- `data_lake/global_financial_conditions_cache.csv` — 41 cột (11 raw + derived + z + pct + PCA + smooth + regime + driver)
- `data_lake/daily_cache/global_financial_conditions_<provider>_<ddmmyy>.txt` — AI analysis text

---

## 10. Mapping config

Constants ở [tools/global_financial_conditions/quant/metrics.py](../tools/global_financial_conditions/quant/metrics.py):

```python
FRED_SERIES = {
    "VIX": "VIXCLS",
    "HY_OAS": "BAMLH0A0HYM2",
    "CCC_OAS": "BAMLH0A3HYC",
    "IG_OAS": "BAMLC0A0CM",
    "EM_OAS": "BAMLEMCBPIOAS",
    "T10Y2Y": "T10Y2Y",
}
YAHOO_TICKERS = {
    "MOVE": "^MOVE",
    "SKEW": "^SKEW",
    "OVX": "^OVX",
    "VVIX": "^VVIX",
    "DXY": "DX-Y.NYB",
}

START_DATE = "2003-01-01"
ROLLING_WINDOW = 252        # 1Y
PCT_STRESS = 0.80           # STRESS threshold
PCT_ELEVATED = 0.50         # ELEVATED threshold
PCT_DRIVER_HIGH = 0.80      # Driver flag threshold
PC1_EMA_SPAN = 5            # EMA smoothing span

PCA_COLUMNS = ["VIX", "MOVE", "SKEW", "HY_OAS", "CCC_OAS", "IG_OAS"]
AUX_COLUMNS = ["OVX", "VVIX", "EM_OAS", "T10Y2Y", "DXY"]
```

---

**End of Handbook** · Q&A: tạo issue trên repo `cuocsongthinhvuong8868-sketch/onl_quant-platform`
