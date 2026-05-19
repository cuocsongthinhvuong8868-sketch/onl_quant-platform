# Pairs Trading Research Lab — Manual Handbook

**Phiên bản:** 2026-05-19
**Tool:** `tools/pairs_trading/` (branch B_Micro_Analysis)
**Đối tượng:** Retail trader VN dùng Pairs Trading Lab để phát hiện + monitor cơ hội cointegration.
**Mục tiêu:** Hướng dẫn setup, đọc hiểu output 5 tab, framework quyết định **thủ công** trước khi có tích hợp AI.

> Đây là tool **standalone** — KHÔNG plug vào AI CIO synthesis (xem `docs/skill.md §13.5`). Bạn phải đọc tay từng signal.

---

## Mục lục

1. [Pairs Trading — nguyên lý 60 giây](#1-pairs-trading--nguyên-lý-60-giây)
2. [Setup & dữ liệu cần thiết](#2-setup--dữ-liệu-cần-thiết)
3. [Sidebar — tham số đầu vào](#3-sidebar--tham-số-đầu-vào)
4. [Đọc hiểu 5 tab](#4-đọc-hiểu-5-tab)
5. [Glossary: cointegration / OU / Z-score / Hurst](#5-glossary)
6. [Decision framework thủ công](#6-decision-framework-thủ-công)
7. [Order ticket schema](#7-order-ticket-schema)
8. [Cạm bẫy & cảnh báo](#8-cạm-bẫy--cảnh-báo)
9. [FAQ](#9-faq)

---

## 1. Pairs Trading — nguyên lý 60 giây

Hai cổ phiếu cùng driver kinh tế (ví dụ VCB và CTG — cùng ngân hàng SOE) có **giá riêng có thể trôi**, nhưng **spread giữa chúng dao động quanh trung bình dài hạn**. Khi spread lệch khỏi mean nhiều (đo bằng z-score), ta:

- **Long mã underperform + Short mã outperform** với tỷ lệ β (hedge ratio).
- Chờ spread quay về mean (mean-reversion) → đóng vị thế ăn chênh lệch.

**Edge của pair trade**: market-neutral (không phụ thuộc VNINDEX up/down), thu nhập từ noise quanh equilibrium.

**Điều kiện cần** để pair là "tradeable":
1. **Cointegrated** (Engle-Granger p < 0.05) — spread mean-reverting về dài hạn
2. **Half-life 5-30 phiên** — đủ nhanh để có ROI, đủ chậm để không bị noise
3. **Hurst < 0.5** — xác nhận mean-reverting, không trending
4. **Liquidity đủ** (volume > 100k CP/phiên cho cả 2 leg)

---

## 2. Setup & dữ liệu cần thiết

### 2.1. Chạy app

```bash
streamlit run app.py
# → home → "🔬 Vào Micro Analysis" → "Pairs Trading Research Lab"
```

### 2.2. Dữ liệu yêu cầu

| File | Update bằng | Tần suất | Bắt buộc? |
|---|---|---|---|
| `data_lake/market_data.csv` | `python command/update_data.py` | Daily | ✅ Bắt buộc (giá close) |
| `data_lake/market_volume.csv` | Cùng lệnh trên | Daily | ⚠️ Optional (lọc liquidity) |
| `data_lake/ticker_metadata.csv` | `python command/update_sector_data.py` | Khi listing mới | ⚠️ Optional (future cluster auto-discovery) |

**Lookback tối thiểu**: 2 năm (~500 phiên) để Johansen + EG ổn định. Mặc định sidebar = 5 năm.

### 2.3. Dependency

```
statsmodels >= 0.14, < 0.16     # coint_johansen, adfuller, vecm
pandas, numpy, scipy
plotly                          # charts
```

Đã có sẵn trong `requirements.txt`.

---

## 3. Sidebar — tham số đầu vào

| Tham số | Default | Ý nghĩa |
|---|---|---|
| **Cluster** | Vingroup | 1 trong 7 cluster predefined (xem §4.1) |
| **Custom pair** | — | Bypass cluster, chọn 2 mã bất kỳ từ universe |
| **Z entry** | 2.0 | \|z\| ≥ 2.0 → entry |
| **Z stop** | 3.0 | \|z\| ≥ 3.0 → stop loss + quarantine |
| **Half-life min** | 5 ngày | Filter — pair có hl < 5 = noise quá nhanh |
| **Half-life max** | 30 ngày | Filter — hl > 30 = vốn kẹt quá lâu, ROI kém |
| **Lookback (năm)** | 5 | Cửa sổ data cho EG/Johansen |
| **Cost (bps round-trip)** | 15 | 10 bps broker + 5 bps slippage. VN sell tax 0.1% đã include phía sell. |
| **Capital (VND)** | 100 triệu | Dùng cho order ticket sizing |

### 7 Cluster predefined

| Cluster | Tickers | Note |
|---|---|---|
| **Vingroup** | VIC, VHM, VRE | ⚠️ Thường FAIL Johansen 95% — VRE thuần retail mall |
| **Big4_Bank** | VCB, CTG, BID | SOE only, 3-way Johansen |
| **Steel** | HPG, HSG, NKG | Cùng input cost (quặng + than) |
| **Securities** | SSI, HCM, VND, VCI | Cùng beta thị trường |
| **Private_Bank** | VPB, STB, ACB, SHB, MBB, HDB | 6-way commercial bank (MBB = Quân Đội, không phải SOE) |
| **Oil_Gas** | GAS, PLX, BSR, PVS | BSR/PVS UPCOM — có thể thiếu trong universe |
| **Utility** | REE, GEX, POW, HDG | Mixed regulated + private utility |

---

## 4. Đọc hiểu 5 tab

### 4.1. Tab 1 — Cluster Scan (Johansen test)

**Output chính**:
- `n_coint_vectors`: số vector cointegration tại 95% CI (range 0 → N-1)
- `trace_stat` vs `trace_crit_95`: nếu trace > crit → reject H0 (không có cointegration), confirm có vector
- **Dominant spread**: linear combo của N mã (weight = eigenvector chính), plot time-series + z-score
- **Half-life** của dominant spread

**Đọc nhanh**:

| n_coint_vectors | Trade được? |
|---|---|
| 0 | ❌ Không — cluster không cointegrated 95%, **bỏ** (vd. Vingroup hiện tại) |
| ≥ 1 | ✅ Có vector tradeable, focus vào dominant spread + check half-life |
| = N-1 | ⚠️ Tất cả mã cùng share, nhưng có thể là spurious — verify bằng pairwise (tab 2) |

🎯 **Action**: nếu n ≥ 1 + half-life 5-30 → entry khi |z_dominant| > 2.

### 4.2. Tab 2 — Pairwise Heatmap

NxN matrix p-value của Engle-Granger cho từng cặp mã trong cluster.

**Đọc màu**:
- 🟥 **Đỏ đậm** (p < 0.01): cointegrated mạnh
- 🟧 Cam (p < 0.05): cointegrated 95%
- 🟨 Vàng (0.05 - 0.1): borderline, không trade
- ⬜ Trắng (p > 0.1): không cointegrated

🎯 **Action**: pick 2-3 cặp đỏ đậm nhất → vào tab 3 verify chi tiết.

**Edge case**: heatmap đỏ đều toàn cluster → có thể do **common trend** (chung 1 market factor) chứ không phải pair edge thật. Verify Johansen ở tab 1: nếu n_coint = 1 (không phải N-1), có thể chỉ 1 vector chung.

### 4.3. Tab 3 — Custom Pair (full pipeline)

Pick 2 mã bất kỳ từ universe `tickers.csv`. Output:

| Metric | Ý nghĩa | Pass criteria |
|---|---|---|
| **β (hedge ratio)** | Số CP mã 2 long/short cho 1 CP mã 1 | 0.3 - 3.0 (ngoài range = đòn bẩy quá lệch) |
| **α (intercept)** | Offset OLS | Không dùng để trade, chỉ check fit |
| **ADF p-value** | Augmented Dickey-Fuller trên residual | **< 0.05** |
| **Half-life (OU)** | `ln(2)/θ` từ AR(1) fit | **5-30 ngày** |
| **Hurst exponent** | R/S analysis | **< 0.5** (mean-reverting) |
| **Z-score hiện tại** | (spread − μ_60d) / σ_60d | \|z\| > 2 → entry signal |
| **Spread chart** | 2-row Plotly: spread + z với band ±2 / ±3 | Visual check |
| **Residual diagnostics** | ACF của residual | Nên decay nhanh (mean-reverting) |

🎯 **Decision tree custom pair**:

```
ADF p < 0.05 ?
  No → STOP, không cointegrated
  Yes ↓
Half-life ∈ [5, 30] ?
  No → STOP (quá nhanh/chậm, không tradeable)
  Yes ↓
Hurst < 0.5 ?
  No → STOP (trending, không mean-revert)
  Yes ↓
|z| hiện tại > 2 ?
  No → WAIT, monitor daily
  Yes → ENTRY (long mã có z âm, short mã có z dương theo β)
```

### 4.4. Tab 4 — Aggregate Backtest

Backtest portfolio đa pair (tất cả pair cointegrated trong cluster pass filter) qua 2 năm gần nhất, **net cost 15 bps**.

**Output**:
- Equity curve (gross + net)
- Drawdown chart
- Hit rate (% trade profit)
- Sharpe ratio net cost
- Turnover annualized

**Acceptable threshold cho retail VN**:

| Metric | Bad | OK | Good |
|---|---|---|---|
| Sharpe (net) | < 0.5 | 0.5 - 1.2 | > 1.2 |
| Hit rate | < 50% | 55-65% | > 65% |
| Max DD | > 15% | 8-15% | < 8% |
| Turnover/năm | > 20x | 8-20x | < 8x (cost-efficient) |

⚠️ **Backtest qua 1 regime duy nhất** = over-fit. Verify pair pass cả Q1 2020 (COVID crash) + 2022 bear + 2024 sideways.

### 4.5. Tab 5 — Live Signals + Order Ticket

Bảng tất cả pair cointegrated × `current_z` × action recommendation. Sort theo |z| giảm dần.

| Cột | Đọc |
|---|---|
| Pair | "VCB / CTG" |
| z_current | Z-score hôm nay |
| Action | LONG_LEG1 / SHORT_LEG1 / WAIT / EXIT |
| Half-life | Số phiên expected để z về 0 |
| Days since last refit | Số ngày kể từ lần fit EG/Johansen |

**Banner trên tab**:
- 🍱 **Lunch break** (11:30-13:00 ICT): order sẽ queue, không execute → đừng kỳ vọng fill ngay
- 🔄 **Refit stale** (> 60 ngày): bấm "Refit Now" để re-test cointegration, tránh trade pair đã break
- 🌏 **FOL** (Foreign Ownership Limit): app assume room > 5%, **verify thủ công** trên web HOSE trước khi đặt lệnh

**Nút "Generate Order Ticket"** → download JSON (xem §7).

---

## 5. Glossary

### Cointegration (Engle-Granger 2-step)
- Step 1: OLS `log(P1) = α + β·log(P2) + ε`
- Step 2: ADF test trên residual `ε`. Nếu p < 0.05 → stationary → cointegrated.

### Johansen test
Multi-variate cointegration (N ≥ 2). Đếm số "vector cointegration" độc lập. Mạnh hơn EG cho cluster ≥ 3 mã.

### OU Half-life (Ornstein-Uhlenbeck)
Fit AR(1): `Δspread_t = θ·(μ − spread_{t-1}) + ε`. Half-life = `ln(2) / θ`. Đại ý: bao nhiêu phiên để spread đi nửa quãng về mean.

### Z-score 60d
`z = (spread_t − rolling_mean_60d) / rolling_std_60d`. Đo độ lệch hiện tại so với "bình thường" 60 phiên gần nhất.

### Hurst exponent
- H < 0.5: mean-reverting
- H ≈ 0.5: random walk
- H > 0.5: trending (KHÔNG dùng pair trade)

### Quarantine
Khi |z| > 3.0 → spread có thể đã structural-break (vd. corp-action, M&A). Đưa pair vào quarantine 60 phiên, không re-entry cho đến khi refit confirm vẫn cointegrated.

---

## 6. Decision framework thủ công

Khi chưa có AI synthesis, dùng workflow 4 bước:

### Bước 1 — Cluster pre-screen (5 phút)

Vào **Tab 1** cho từng cluster:
- Loại cluster có `n_coint_vectors = 0` (vd. Vingroup hiện tại).
- Giữ cluster có n ≥ 1 + half-life 5-30.

### Bước 2 — Pair zoom (10 phút)

Vào **Tab 2** cluster đã pass → identify 2-3 pair đỏ đậm nhất.
Vào **Tab 3** từng pair → run decision tree §4.3.

### Bước 3 — Backtest verify (10 phút)

Vào **Tab 4** cluster đã pass → check:
- Sharpe net ≥ 0.8
- Max DD ≤ 12%
- Equity curve smooth, không có 1 trade duy nhất gánh toàn bộ P&L

### Bước 4 — Live check + execution (5 phút)

Vào **Tab 5**:
- Sort theo |z| → focus pair có |z| > 2 hiện tại
- Check half-life ∈ filter band, days_since_refit < 60
- Click **Generate Order Ticket** → download JSON → đặt lệnh thủ công trên broker

**Position sizing**:
- Tối đa 5% NAV / pair
- Tối đa 25% NAV / cluster (tránh concentrated cluster risk)
- Hedge ratio β đúng theo ticket (sai β = không market-neutral)

---

## 7. Order ticket schema

JSON download từ Tab 5:

```json
{
  "timestamp": "2026-05-19T09:15:00+07:00",
  "pair": ["VCB", "CTG"],
  "legs": [
    {"ticker": "VCB", "side": "SELL", "quantity": 300, "limit_price": 92500},
    {"ticker": "CTG", "side": "BUY",  "quantity": 1100, "limit_price": 34200}
  ],
  "hedge_ratio": 0.27,
  "z_at_entry": 2.14,
  "expected_half_life_days": 12,
  "stop_z": 3.0,
  "margin_required": 18500000,
  "notes": "Lunch break 11:30-13:00 ICT — do not auto-execute"
}
```

**Quantity** đã làm tròn về bội số 100 (lot size HOSE). **Margin** tính theo tỷ lệ 50% + 2× cushion cho swing intra-day.

⚠️ **App không tự đặt lệnh** — bạn phải copy số liệu sang web broker thủ công. Đây là design choice (xem §13.5 spec — pairs signal orthogonal AI CIO).

---

## 8. Cạm bẫy & cảnh báo

1. **Corp-action**: split / cổ tức bằng tiền không adjust → spread sẽ fake-jump tại ngày ex-date. Check lịch corp-action trên cafef trước khi entry.
2. **Vingroup cluster** thường FAIL Johansen 95% — VRE thuần retail mall vs VIC/VHM RE đã divergent fundamentals từ 2023.
3. **FOL**: VCB, FPT, MWG room ngoại thường < 1% → có thể không match được lệnh. Check `cafef.vn/du-lieu/<ticker>.chn` cột "Room ngoại".
4. **T+2 settlement**: VN không cho intra-day pair (close cùng phiên). Half-life < 3 ngày = không thực thi được.
5. **Lunch break 11:30-13:00 ICT**: lệnh queue, không thực thi → nếu z spike trong 11:30-13:00, entry sẽ slip.
6. **UPCOM tickers** (BSR, PVS, một số mã Oil_Gas): liquidity mỏng, bid-ask spread rộng → cost > 15 bps. Tăng cost lên 30-50 bps khi backtest.
7. **Cluster cointegration ≠ pair cointegration**: Johansen pass cluster KHÔNG có nghĩa mọi pair đều tradeable. Luôn verify pairwise tab 2.
8. **Survivorship**: cluster predefined chỉ chứa mã đang list. Pair với mã bị delist (vd. POW giai đoạn pre-2020) không backtest được.
9. **Refit stale > 60 ngày**: cointegration không vĩnh viễn — break do M&A, change of business, regulation. Refit định kỳ.
10. **Aggregate Backtest cache**: kết quả cache theo `data_date = df.index[-1]`. Nếu data chưa update → backtest dùng data cũ, KHÔNG phải today.

---

## 9. FAQ

**Q: Tại sao không plug Pairs Trading vào AI CIO executive summary?**
A: Pairs signal là per-pair, per-day, **discrete event** (long VCB / short CTG, z = -2.3, half-life 12d). Không aggregate được vào "regime score 0-100". Spec §13.5 — orthogonal.

**Q: Tôi muốn thêm cluster mới (vd. Real Estate non-Vingroup)?**
A: Sửa `tools/pairs_trading/quant/clusters.py:PREDEFINED_CLUSTERS`. Rule: cùng economic driver + regulatory regime + FOL profile.

**Q: Half-life trả về NaN?**
A: Hoặc spread không mean-revert (θ ≤ 0), hoặc half-life ngoài filter band 5-30. Bỏ pair.

**Q: Sharpe backtest 1.5 nhưng live trade lỗ — sao vậy?**
A: Check (1) cost thực ≥ 15 bps không? slippage? (2) over-fit 1 regime? (3) data có bias survivorship? (4) corp-action chưa adjust? Thường nguyên nhân ở (1) hoặc (4).

**Q: Có thể chạy Pairs Trading trên Streamlit Cloud Free tier?**
A: Có, nhưng cluster 6-way (Private_Bank) Johansen có thể timeout 60s. Streamlit Cloud free CPU yếu — cân nhắc giảm lookback xuống 3 năm hoặc cache aggressive.

**Q: Cointegration vs Correlation khác gì?**
A: Correlation đo **co-movement ngắn hạn** (có thể giả do common trend). Cointegration đo **equilibrium dài hạn** — spread stationary. Correlation cao + không cointegrated = spurious, không tradeable.

**Q: Tại sao default cost 15 bps?**
A: VN typical: 0.10% broker fee (round-trip 20 bps) + 0.10% sell tax (chỉ phía sell, 10 bps) − bù trừ trên 2 leg ≈ 15 bps net round-trip. Tăng lên 25 bps nếu broker fee cao hoặc trade mã UPCOM.

---

**Liên quan**:
- Spec gốc: `docs/skill.md §13` (Pairs Trading Research Lab)
- Ship log: `docs/skill.md §14` (delta vs plan, file changed)
- Code: `tools/pairs_trading/` + `shared/dcc_garch.py` (cross-utility cho future filter)
- Cluster definition: `tools/pairs_trading/quant/clusters.py`
