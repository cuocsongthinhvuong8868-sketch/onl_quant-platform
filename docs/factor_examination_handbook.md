# Factor Examination Handbook

**Tool**: Portfolio Factor Examination — multi-factor cross-sectional stock scorer
**Module**: `tools.factor_examination`
**Page**: Nhánh B (Micro Analysis)
**Ngày phát hành**: 2026-05-20

---

## 1. Mục tiêu

Trả lời 1 câu hỏi cụ thể: **"Trong universe VN ~250 mã, ticker nào đứng tốt hơn phần còn lại trên 10 factor đồng thời?"** — và áp dụng câu hỏi đó cho **portfolio của bạn**: holdings nào mạnh, holdings nào yếu, portfolio đang **tilt** vào phong cách đầu tư nào.

> ⚠️ **Đây KHÔNG phải regime classifier.**
> Tool không trả lời "thị trường bull hay bear", "nên risk-on hay risk-off", "factor nào sẽ outperform tháng tới". Đó là việc của:
> - **GFCM** (Global Financial Conditions Monitor) — quyết định macro regime
> - **ESR Monitor** — quyết định domestic VN regime
> - **Market Breadth / Dispersion** — đánh giá market state
> - **Bạn (human in the loop)** — diễn giải tất cả để quyết regime
>
> Factor Examination chỉ có alpha **sau khi bạn đã quyết regime** từ các tool kia. Tool này chỉ trình bày exposure, không khuyến nghị tilt direction.

---

## 2. 10 Factor — Định nghĩa & Direction

Tất cả factor đã **sign-orient "higher = better"** theo academic prior. Nghĩa là z-score dương = ticker đó "tốt" hơn trung bình sector trên factor đó (theo định nghĩa academic).

### Momentum group (3 factor)
| Factor | Formula | Window | Intuition |
|---|---|---|---|
| **Mom_12_1** | return(t-21 → t-252) | 12M skip 1M | Đà tăng dài hạn, skip 21d để tránh ST reversal contamination |
| **Mom_6_1** | return(t-21 → t-126) | 6M skip 1M | Đà tăng trung hạn |
| **ST_Reversal** | −return(t → t-21) | 21d | Short-term mean revert: low recent return = chuẩn bị bounce |

### Reversal / Long-term (1 factor)
| Factor | Formula | Window | Intuition |
|---|---|---|---|
| **LT_Reversal** | −return(t-756 → t-1260) | 5Y → 3Y | Long-term mean revert: mã từng underperform 5Y trước có alpha |

### Volatility group (3 factor)
| Factor | Formula | Window | Intuition |
|---|---|---|---|
| **LowVol** | −σ(daily return) | 252d | Low-vol anomaly — vol thấp tạo Sharpe cao về dài hạn |
| **Beta_Low** | −β(stock vs VN-Index) | 60d | Low-beta anomaly — Bali, Brunnermeier |
| **IdioVol_Low** | −σ(residual sau remove market β) | 60d | Idiosyncratic risk không được reward → ưu tiên low idio |

### Liquidity / Size (2 factor)
| Factor | Formula | Window | Intuition |
|---|---|---|---|
| **Liquidity** | −Amihud = −mean(\|r\| / dollar_vol) | 60d | Liquid stocks có lower price impact, easier to scale |
| **Size** | log(median ADV20d) | 20d | Larger ADV proxy market cap — large more stable |

### Anti-lottery (1 factor)
| Factor | Formula | Window | Intuition |
|---|---|---|---|
| **Anti_Lottery** | −max(daily return 21d) − 0.01·skew(return 60d) | 21d/60d | Lottery-like stocks (high MAX, positive skew) attract retail → underperform (Bali-Cakici-Whitelaw 2011) |

> 📌 **Sign convention RECAP**: nếu bạn thấy "LowVol = +1.2σ" trong portfolio exposure, nghĩa là **portfolio tilt vào low-vol stocks** (good side), không phải "portfolio có vol cao". Mọi factor đều theo logic "higher = better side".

---

## 3. Pipeline — Từ raw đến composite

```
1. Raw factor          (10 chiều × N ticker)
       ↓
2. Cross-section z-score
   - Robust: (x − median) / (MAD × 1.4826)
   - Fallback (x − mean) / std nếu MAD = 0
   - Winsorize ±3σ tránh outlier dominate
       ↓
3. Sector-neutralize
   - Map ticker → ICB sector từ `data_lake/ticker_metadata.csv`
   - Sector <5 mã gộp 'Other'
   - z_neutral = z − sector_mean(z)
       ↓
4. Composite z-score
   - Equal-weight mean of 10 factor z-scores
   - Mã có <5 factor valid (out of 10) → composite = NaN
       ↓
5. Percentile rank
   - composite.rank(pct=True) × 100 → vị trí trong universe
```

### Tại sao MAD-based z-score?
- Mean/std z-score nhạy với outlier (vd Mom của 1 mã +500% sẽ đẩy mean lệch)
- MAD = Median Absolute Deviation, robust với fat tail
- Hệ số 1.4826 normalize MAD ↔ Gaussian σ
- Sau đó winsorize ±3σ thêm một tầng bảo vệ

### Tại sao sector-neutralize?
- Bank có σ thấp tự nhiên (low-vol prior) — nếu raw rank thì Bank chiếm top
- Steel có Mom cao trong commodity rally — nếu raw rank thì Steel chiếm top
- Sector-neutral: so sánh **trong sector** trước, rồi gộp lại → fair across sector

### Tại sao equal-weight (không IC-weight)?
- IC-weighted optimal trong-sample dễ overfit (factor nào lucky trong 3Y backtest → weight cao trong forward)
- Equal-weight robust, không cần calibrate
- User-in-loop quyết định weight tilt thông qua portfolio construction (không qua factor weighting)

---

## 4. Đọc 4 Tab

### Tab 1 — Universe Ranking

**Output**:
- Heatmap **Top 20** composite (xanh = mạnh) + **Bottom 20** (đỏ = yếu)
- Histogram composite distribution của universe + đường p10 / p50 / p90
- Bar chart sector composition: top decile vs bottom decile

**Cách dùng**:
- Soi nhanh ai đang **mạnh đều 10 factor** (composite cao + heatmap toàn xanh)
- Phát hiện **sector bias**: nếu top decile concentrated vào 1 sector → có thể là sector rally đang ưu thế, hoặc methodology bias
- Tìm **outlier theo factor cụ thể**: 1 mã có Mom_12_1 = +2.5σ nhưng LowVol = −2.0σ = đang ride momentum cao volatility (rủi ro reversal)

### Tab 2 — Portfolio Examination *(core feature)*

**Input**: portfolio dạng `ticker,weight`
- Paste text: `VIC, 0.15\nVHM, 0.10\n…` hoặc `VIC, 15%` (tự convert %)
- Upload CSV: cột đầu `ticker`, cột sau `weight`
- Weight tự normalize tổng = 1.0

**Output**:
1. **4 metric cards** ở đầu:
   - Holdings in universe (đã loại ticker không có)
   - Portfolio composite z (weighted sum composite)
   - Estimated rank pct (vị trí portfolio composite trong universe distribution)
   - Concentration alerts (factor nào có |exp| > 1σ)
2. **Radar chart 10 chiều**: portfolio exposure (blue) vs equal-weight universe benchmark (gray dotted)
3. **Concentration alerts table**: list factor có |exp| > 1σ + direction
4. **Sector breakdown**: % weight per sector
5. **Holdings detail**: horizontal bar chart ranked theo composite (green = top quartile rank, red = bottom quartile)
6. **AI section**: 🤖 button tạo phân tích narrative (cần API key sidebar)

**Cách đọc**:
- **Composite z dương + radar tilt rõ ràng** → portfolio có "phong cách" định hướng (Mom-tilt, Defensive, Contrarian, v.v.)
- **Composite z ≈ 0 + radar gần benchmark** → portfolio cân bằng, không bias factor — có thể là intentional (diversify) hoặc thiếu định hướng
- **Composite cao nhưng concentration 1 sector** → idio risk cao (single-bet)
- **Holdings có rank < 25 (red)** → review lại weight cho mã đó, hoặc accept idio rationale (vd: mã đó có catalyst riêng không phản ánh trong factor)

### Tab 3 — Single Ticker Profile

**Input**: chọn ticker từ dropdown

**Output**:
- 4 metric: composite z, rank pct, sector, last close
- Bar chart factor z (sector-neutral) của ticker này — màu xanh/đỏ theo dấu
- Raw factor values (expander)
- **Closest peers** (Euclidean distance trong 10-chiều factor space)

**Cách dùng**:
- Hiểu **why một ticker rank thế nào**: factor nào đẩy lên, factor nào kéo xuống
- Tìm **substitute candidate**: nếu muốn diversify khỏi 1 mã, tìm peer có profile tương tự
- Phát hiện **profile mismatch**: vd ticker được positioning là "growth" nhưng có Mom thấp → narrative đang sai

### Tab 4 — Forward IC Validation

**Compute**: rolling snapshot mỗi 21 phiên trong N năm lookback. Mỗi snapshot:
1. Compute factor + composite as-of date
2. Forward return tại 3 horizon: 21d / 63d / 126d
3. Spearman rank correlation = IC

**Output**:
- **Summary table**: per horizon — n_snapshots, mean_ic, std_ic, ICIR, hit_rate
- **IC time series**: bar chart per horizon + mean line
- **Decile spread cumulative**: top 10% composite vs bot 10% composite (21d holding)

**Cách đọc IC**:
| IC value | Interpretation |
|---|---|
| IC > 0.05 mean (stable) | Composite có positive predictive power |
| IC ≈ 0 | Composite neutral signal — không predict, không anti-predict |
| IC < -0.05 stable | Composite **anti-predict** — top decile underperform (regime mismatch) |
| ICIR > 0.5 | Signal stable across snapshot |
| Hit rate > 55% | Consistent positive bias |

**Caveat**:
- VN sample size nhỏ (1-5Y lookback → 12-60 snapshot)
- IC âm trong 1 cycle không có nghĩa factor "bị hỏng" — có thể regime đảo chiều (vd 2024 small-cap rally → low-vol anomaly đảo)
- **Decile spread âm** trong 1 giai đoạn = small-cap / lottery stocks outperform → tool composite tilt sai phía

---

## 5. Workflow đề xuất (human-in-the-loop)

```
┌─────────────────────────────────────────────────┐
│ Step 1: Đọc REGIME từ tool macro/micro          │
│   - GFCM: stress / elevated / calm + driver     │
│   - ESR: regime VN state                        │
│   - Market Breadth: trend health                │
│   - Dispersion: cross-section coherence         │
└─────────────────┬───────────────────────────────┘
                  ↓
┌─────────────────────────────────────────────────┐
│ Step 2: Mở Factor Examination                   │
│   Tab 1: Soi universe — top decile sector?      │
│   Tab 4: IC backtest — composite còn predict?   │
└─────────────────┬───────────────────────────────┘
                  ↓
┌─────────────────────────────────────────────────┐
│ Step 3: Nhập portfolio (Tab 2)                  │
│   - Radar: portfolio đang tilt phong cách nào?  │
│   - Concentration alerts: factor nào > 1σ?      │
└─────────────────┬───────────────────────────────┘
                  ↓
┌─────────────────────────────────────────────────┐
│ Step 4: Cross-check với regime đã đọc           │
│   STRESS regime + portfolio tilt high-Beta?     │
│     → Mismatch! Cân nhắc reduce                 │
│   CALM bull + portfolio tilt LowVol?            │
│     → Đang underexpose, có thể tăng risk        │
│   Vẫn neutral → portfolio không bias, OK        │
└─────────────────┬───────────────────────────────┘
                  ↓
┌─────────────────────────────────────────────────┐
│ Step 5: Per-holding review (Tab 2 bar chart)    │
│   - Holdings rank red → review weight           │
│   - Tab 3 deep-dive ticker yếu nhất             │
└─────────────────────────────────────────────────┘
```

---

## 6. Concentration alert — Đọc nâng cao

Alert trigger khi `|factor_exposure| > 1σ`. Mỗi alert ý nghĩa:

| Direction | Ý nghĩa | Risk nếu regime đảo |
|---|---|---|
| **Mom_12_1 +1σ** | Portfolio nặng momentum dài hạn | Reversal khi sentiment shift |
| **Mom_6_1 +1σ** | Tilt momentum trung hạn | Short-cycle reversal |
| **ST_Reversal +1σ** | Tilt vào low recent return (contrarian ngắn hạn) | Trend continuation đốt cháy |
| **LT_Reversal +1σ** | Contrarian long-term | Mã underperform 5Y vẫn tiếp tục underperform |
| **LowVol +1σ** | Defensive tilt | Bull rally khiến defensive underperform |
| **Beta_Low +1σ** | Low-beta tilt | Bull breakout cần high-beta |
| **IdioVol_Low +1σ** | Low idio (clean systematic exposure) | Idio events tích cực bỏ lỡ |
| **Liquidity +1σ** | Liquid large-cap | Microcap rally bỏ lỡ |
| **Size +1σ** | Large-cap tilt | Small-cap premium bỏ lỡ |
| **Anti_Lottery +1σ** | Avoid high-MAX stocks | Lottery rally (meme) bỏ lỡ |

| Direction âm | Ý nghĩa | Risk |
|---|---|---|
| **Mom_12_1 −1σ** | Tilt anti-momentum / mới giảm mạnh | Falling knife risk |
| **LowVol −1σ** | Tilt high-vol | Drawdown lớn khi vol spike |
| **Beta_Low −1σ** | Tilt high-beta | Crash amplified |
| **Liquidity −1σ** | Tilt microcap | Liquidity squeeze, slippage cao |
| **Size −1σ** | Tilt small-cap | Vol cao, drawdown sâu |

> 📌 Concentration **không phải báo "xấu"** — chỉ là **info**. Tilt mạnh là conscious choice nếu human đã đọc regime đúng. Tool flag để bạn check intent vs accident.

---

## 7. Limitations

### a) Price-based only — không có fundamental
- Không Value (P/E, P/B), Quality (ROE, debt), Growth (revenue growth)
- Lý do: vnstock Community (free) chỉ 8 quý BCTC → 2Y sample bias quá nặng cho Value/Quality
- Defer P2 khi có vnstock Sponsor paid

### b) Static factor weight, không regime-conditional
- Equal-weight 10 factor trong mọi regime
- Lý do: human-in-the-loop pattern — bạn quyết định regime đã đủ, không cần tool auto-tilt
- Trade-off: trong STRONG bull, LowVol và Beta_Low tilt sẽ persistently negative → biết trước

### c) IC backtest sample size hạn chế
- Max 5Y lookback → ~60 snapshots
- IC mean SE ≈ 0.13 — khó claim significant predictive power tin cậy
- IC chủ yếu dùng để **sanity check** ("composite không anti-predict"), không phải để optimize weights

### d) Universe filter ADV
- Mặc định ≥ 1 tỷ VND/ngày median 20d → cover ~80-130 mã
- Quá thấp → microcap noise; quá cao → universe nhỏ thiếu cross-section power
- 1 tỷ VND ≈ 40k USD/day, hợp lý cho retail VN

### e) Sector mapping ICB
- 245/253 mã có ICB từ `data_lake/ticker_metadata.csv`
- ETF/futures (FUEV*, E1VFVN30, VN30F1M) bị exclude
- Sector <5 mã gộp 'Other' — Insurance / Tech / một số ngành nhỏ rơi vào 'Other'

### f) Tool tự thân **không** sinh alpha
- Composite không phải signal trading
- Top decile cumulative không guarantee outperform
- Output cần **bạn diễn giải kết hợp regime tool khác**

---

## 8. So sánh với tool khác trên platform

| Câu hỏi cần trả lời | Tool nào |
|---|---|
| Macro regime (global FCI)? | **GFCM** |
| Domestic VN regime? | **ESR Monitor** |
| Market trend health (% > MA)? | **Market Breadth** |
| Cross-section coherence (đồng pha hay phân kỳ)? | **Dispersion** |
| Tail risk VN-Index? | **VaRES / Var-CVaR VNINDEX** |
| Fear/Greed retail sentiment? | **Fear & Greed** |
| Manipulation VIC/VHM/VRE? | **Manipulation** |
| Pair trading cointegration? | **Pairs Trading** |
| **"Portfolio TÔI đang exposure phong cách gì? Holdings nào mạnh/yếu?"** | **Factor Examination** ← bạn ở đây |

**Factor Examination orthogonal** với tất cả tool khác — không double count. Tool khác trả lời "thị trường đang sao", Factor Examination trả lời "danh mục bạn đang sao".

---

## 9. Operational

### Cache
- Score table: `@st.cache_data ttl=86400` (24h)
- Cache key = (latest_data_date, universe_hash, sector_neutral_flag, "v1")
- IC backtest: same TTL, separate key

### Data dependencies
- `data_lake/market_data.csv` — close prices
- `data_lake/market_volume.csv` — daily volume
- `data_lake/vnindex_cache.csv` — VN-Index cho beta
- `data_lake/ticker_metadata.csv` — ICB sector

### Backfill yêu cầu
- Cho **đầy đủ** 10 factor: cần ≥ 5Y + 21d buffer = **~1300 trading days**
- Chạy `python command/update_data.py --backfill 2190` (6Y) là đủ
- Mã thiếu data cho LT Reversal → NaN cho factor đó, composite vẫn compute nếu có ≥5 factor valid

### AI cost
- Standalone AI tab, mỗi portfolio analysis = 1 call OpenAI/Kimi/DeepSeek (~$0.005 per call với Kimi 2.6)
- KHÔNG inject vào executive summary (giữ scope sạch — exec sum là 9 VN-equity tools only)

---

## 10. FAQ

**Q1**: Tại sao composite của portfolio rất gần 0 dù holdings có rank cao?
- Có thể do **sector dispersion**: holdings ở nhiều sector khác nhau, mỗi sector top performer khác nhau → sau sector-neutralize triệt tiêu
- Hoặc holdings ranking cao trên factor riêng lẻ nhưng diverge nhau → mean ≈ 0

**Q2**: Composite âm có phải là "portfolio xấu"?
- KHÔNG nhất thiết. Composite âm = portfolio đang ngược với "academic prior" 10 factor.
- Có thể là conscious choice: vd portfolio tilt high-beta + high-Mom (chấp nhận risk cho upside)
- Cần đọc cùng regime: nếu CALM bull regime → tilt risk-on có lý

**Q3**: Tại sao IC mean của tôi gần 0?
- Equal-weight composite **không calibrate** cho window backtest cụ thể → IC trung bình ~0 trong sample 2-3Y là bình thường
- Quan trọng là **không anti-predict** (IC âm stable < -0.1)
- IC dương stable > 0.05 = bonus, không phải requirement

**Q4**: Tôi có thể custom weight không?
- Hiện tại không (equal-weight fixed)
- Lý do design: tránh user overfit weights theo gut feeling
- Nếu cần custom analysis → fork code, edit `composite_score()` trong `quant/scoring.py`

**Q5**: Tool có replace research fundamental không?
- KHÔNG. Tool là **price-based**, không thấy được catalyst riêng, earnings surprise, M&A, regulatory shift
- Fundamental research → research kỹ từng mã (BCTC, ban lãnh đạo, narrative)
- Factor Examination → **layer trên cùng** để check portfolio aggregate exposure

---

## 11. Version log

| Date | Version | Note |
|---|---|---|
| 2026-05-20 | v1.0 | Initial ship — 10 factor, equal-weight, sector-neutral ICB |
| (future) | v1.1 | Có thể add: factor weight slider, custom factor add, time-series IC chart per factor |
| (future P2) | v2.0 | Thêm Value/Quality/Growth khi có vnstock Sponsor paid (BCTC 5Y) |
