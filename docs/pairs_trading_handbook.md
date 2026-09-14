# Pairs Trading Research Lab v2 — Manual Handbook

**Phiên bản phương pháp:** `pairs_research_point_in_time_v2`

**Cập nhật:** 2026-09-14

**Tool:** `tools/pairs_trading/` trong nhánh B. Micro Analysis

**Phạm vi:** research và tạo ticket thủ công; không tự gửi lệnh cho broker.

## 1. Điều gì đã thay đổi ở v2

V2 tách rõ ba lớp quyết định:

1. **Statistical validity** — Engle–Granger dùng MacKinnon p-value, hai leg phải I(1), nhiều pair được kiểm soát bằng BH-FDR; Johansen có kiểm tra I(1), lag và full-rank.
2. **Research eligibility** — q-value, half-life, beta dương, beta stability và dynamic-correlation gate tùy chọn.
3. **Execution readiness** — freshness/common quote, adjusted-price provenance, ADV, borrow inventory/fee, shortability và FOL đều phải pass mới mở download ticket.

Backtest v2 là walk-forward: model chỉ fit trên formation window ở quá khứ, refit theo cadence cấu hình, z-score tại phiên `t` chỉ dùng location/scale đến `t-1`. P&L được gross-normalize và trừ broker/slippage một chiều, thuế bán và borrow cost riêng.

## 2. Dữ liệu và provenance

| Dataset | Vai trò | Cập nhật |
|---|---|---|
| `data_lake/market_data.csv` | Close price | `python command/update_data.py` |
| `data_lake/market_volume.csv` | Mask stale/suspended quotes và tính median ADV20 | Cùng lệnh trên |
| `data_lake/ticker_metadata.csv` | Industry/exchange cho universe scanner | `python command/update_sector_data.py` |

Snapshot loader loại giá không dương/không hữu hạn, deduplicate ngày và chỉ dùng volume để mask zero-volume quote khi coverage của ticker đủ tin cậy. Mỗi snapshot có fingerprint và `data_as_of` để chống dùng nhầm cache cũ.

Hai hạn chế provenance hiện được hiển thị công khai:

- Nguồn giá hiện tại chưa cung cấp cờ adjusted-price có thể kiểm chứng tự động. Vì vậy app mặc định đánh dấu `adjusted_verified=false`; người dùng phải đối soát corporate action trước khi mở ticket.
- Industry/universe file là current-state, chưa phải point-in-time membership. Scanner phù hợp để tìm candidate hiện tại; không được diễn giải như backtest universe không survivorship bias.

## 3. Pipeline thống kê

### Engle–Granger

Orientation được định nghĩa một lần:

```text
log(P1) = alpha + beta * log(P2) + residual
```

Tool không còn thử cả hai orientation rồi lấy p-value nhỏ nhất. `statsmodels.coint(..., method="aeg", autolag="aic")` cung cấp cointegration statistic và MacKinnon p-value đúng cho Engle–Granger. Cả `log(P1)` và `log(P2)` phải non-stationary ở level nhưng stationary ở first difference.

Khi test nhiều pair, quyết định dựa trên **BH-FDR q-value**, không dựa riêng raw p-value. Raw p vẫn hiển thị để audit.

### Johansen

Johansen dùng log-prices có common observations, chọn VAR lag theo BIC, kiểm tra mọi series là I(1), và vô hiệu hóa kết quả full-rank vì full-rank không phải một hệ I(1) cointegrated hợp lệ.

### Half-life và Hurst

Half-life được suy từ AR(1):

```text
spread_t = c + phi * spread_(t-1) + error_t
half_life = -log(2) / log(phi), với 0 < phi < 1
```

Tool trả thêm khoảng tin cậy 95% xấp xỉ của half-life. Hurst vẫn là diagnostic phụ; research gate chính là cointegration/FDR, half-life, beta/stability và correlation nếu bật.

### Z-score và dynamic correlation

- `standard`: rolling mean/std.
- `robust`: rolling median/MAD.
- `ewma`: exponentially weighted mean/std.

Cả ba estimator mặc định lag một phiên. Historical walk-forward dùng causal EWMA correlation; DCC MLE chỉ dùng cho current-as-of diagnostics, và UI ghi rõ nếu DCC không hội tụ rồi fallback sang EWMA.

## 4. Sidebar

| Nhóm | Tham số chính | Mặc định |
|---|---|---|
| Signal | Entry / stop | 2.0 / 3.0 |
| Signal | Z estimator | standard |
| Eligibility | Half-life band | 5–30 sessions |
| Eligibility | Require stable hedge ratio | bật |
| Correlation | Dynamic-correlation gate | tắt; EWMA khi bật |
| Walk-forward | Formation / refit | 252 / 20 sessions |
| Sizing challenger | OLS / rolling / Kalman | OLS |
| Costs | Broker+slippage one-way | 15 bps |
| Costs | Sell tax / borrow | 10 bps / 500 bps năm |
| Capacity | Min median ADV20 mỗi leg | 1 tỷ VND |
| Portfolio | Max allocation mỗi pair | 25% |

Rolling/Kalman là causal sizing challenger. Engle–Granger OLS vẫn quyết định statistical eligibility để tránh thay đổi null test theo model sizing.

## 5. Sáu tab

### Cluster Scan

Chạy Johansen cho cluster đang chọn, hiển thị raw/effective rank, selected lag và mọi guardrail warning. Dominant vector chỉ được vẽ khi hệ hợp lệ và effective rank lớn hơn 0.

### Pairwise FDR

Chạy đúng một orientation cho mỗi unordered pair. Heatmap hiển thị q-value BH, bảng audit có raw p, q, I(1), beta và số quan sát. Correlation heatmap là context ngắn hạn, không thay thế cointegration.

### Universe Scanner

Funnel:

```text
industry/exchange bucket
  -> trailing return correlation
  -> proper EG + I(1)
  -> BH-FDR across all tested survivors
  -> exact half-life
  -> beta stability
  -> median ADV20 capacity
```

Score chỉ để xếp hạng các candidate đã pass. Cache key gồm dataset fingerprint và toàn bộ filter; kết quả stale bị chặn khi data/filter đổi. Nút pre-fill đưa candidate vào Custom Pair.

### Custom Pair

Hiển thị current formation diagnostics và walk-forward out-of-sample backtest từ cùng canonical engine. Residual chart dùng cointegration statistic thật. Expander cung cấp trade ledger và từng point-in-time refit, gồm `model_as_of`, p-value, I(1), half-life, stability và lý do bị chặn.

### Portfolio Backtest

Mọi pair trong cluster dùng family-wise alpha Bonferroni, cùng formation/refit/cost config. Pair allocation được cố định ex ante và capped; phần chưa phân bổ là cash. Các leg trùng ticker được net trước khi tính turnover, sell tax, borrow cost và gross/net exposure. Kết quả không phải phép cộng độc lập các net equity curve.

### Live Signals

Research signal chỉ xuất hiện khi current pair pass I(1), cluster-level BH-FDR, half-life, beta và các gate bật trong sidebar. Stop `|z| >= stop` được xử lý trước entry và kích hoạt quarantine 60 trading sessions.

Một entry signal vẫn có thể hiện là `ticket=BLOCKED`. Download chỉ mở khi:

- adjusted prices/corporate actions đã đối soát;
- data đủ fresh và hai leg có common quote tại data-as-of;
- model-as-of trùng data-as-of;
- median ADV20 của từng leg đạt ngưỡng;
- borrow inventory/fee, shortability và FOL đã được xác nhận.

## 6. Walk-forward và P&L

Mỗi refit:

1. Fit EG/I(1), half-life và beta stability trên formation window kết thúc trước trading block.
2. Giữ model cố định trong block kế tiếp; rolling z dùng observations đến `t-1`.
3. Gate entry theo trạng thái model và causal correlation.
4. Refit sau số sessions cấu hình.

Position weights được gross-normalize:

```text
w1 = position / (1 + |beta|)
w2 = -position * beta / (1 + |beta|)
```

Do đó gross exposure của một pair active xấp xỉ 1. P&L dùng prior weights cho return `t-1 -> t`; target mới tại close `t` chịu turnover cost tại `t`. Backtest mặc định liquidate ở cuối mẫu để không bỏ phí đóng lệnh.

Các cost line item:

- broker/slippage trên toàn traded notional, một chiều;
- sell tax chỉ trên notional bán;
- borrow cost hằng ngày trên short exposure;
- ledger tính net return theo từng completed position episode; win rate là trade-level, không phải tỷ lệ ngày dương.

## 7. Signal state machine

| Trạng thái/event | Điều kiện |
|---|---|
| Long spread | `-stop < z <= -entry` và mọi gate pass |
| Short spread | `entry <= z < stop` và mọi gate pass |
| Mean-revert exit | Long khi `z >= -exit_band`; short khi `z <= exit_band` |
| Time stop | Holding sessions đạt `ceil(2 * half_life)` |
| Eligibility exit | Point-in-time gate fail trong khi đang giữ |
| Breakdown | `|z| >= stop`; flat ngay, rồi quarantine |

Trong quarantine không được re-entry dù z quay lại entry band. Quarantine được đếm theo observations/trading sessions, không theo calendar days.

## 8. Ticket v2

Ticket là JSON strict (`NaN` bị từ chối), timestamp timezone-aware `Asia/Ho_Chi_Minh`, có UUID, expiry 15 phút, `data_as_of`, `model_as_of` và execution-check audit.

Schema rút gọn:

```json
{
  "schema_version": "pair_order_ticket_v2",
  "ticket_id": "uuid",
  "timestamp": "2026-09-12T09:15:00+07:00",
  "expires_at": "2026-09-12T09:30:00+07:00",
  "research_only": true,
  "data_as_of": "2026-09-11",
  "model_as_of": "2026-09-11",
  "pair": ["VCB", "CTG"],
  "legs": [
    {"ticker": "VCB", "side": "SELL", "quantity": 300, "reference_price": 92500.0},
    {"ticker": "CTG", "side": "BUY", "quantity": 800, "reference_price": 34200.0}
  ],
  "hedge_ratio_beta": 1.0,
  "z_at_entry": 2.14,
  "expected_half_life_sessions": 12.0,
  "execution_checks": {
    "adjusted_price_verified": true,
    "borrow_confirmed": true,
    "foreign_room_verified": true,
    "short_leg_is_shortable": true,
    "fresh_data": true,
    "common_quote": true,
    "liquidity_ok": true,
    "model_current": true
  }
}
```

Ticket dùng reference close, không phải executable bid/ask. Luôn revalidate price band, quote, borrow và room trên broker trước khi đặt lệnh.

## 9. Cạm bẫy còn lại

- **Corporate actions:** override adjusted-price là xác nhận thủ công có trách nhiệm, không phải cách bỏ qua cảnh báo.
- **Shorting tại Việt Nam:** research signal không đồng nghĩa có thể short cash equity. Chỉ tạo ticket nếu broker/product thực tế hỗ trợ leg đó.
- **Survivorship:** current-state cluster/metadata làm lịch sử đẹp hơn thực tế; cần point-in-time membership trước khi dùng cho production capital.
- **Parameter mining:** không chọn formation, z method và thresholds theo Sharpe cao nhất trên cùng một mẫu.
- **Capacity:** ADV không mô hình hóa spread/market impact đầy đủ; tăng slippage và giảm allocation cho UPCOM hoặc mã có book mỏng.
- **Regime break:** cointegration không vĩnh viễn; beta stability, correlation và quarantine chỉ giảm rủi ro, không loại bỏ nó.
- **Multiple testing:** custom pair do thesis định trước có thể đọc raw p; scanner/live cluster phải dùng q-value.

## 10. Workflow đề xuất

1. Kiểm tra quality panel và data-as-of.
2. Dùng Pairwise FDR hoặc Universe Scanner để tạo candidate set.
3. Mở Custom Pair, đọc I(1), p/q, half-life CI, beta stability và warnings.
4. Chỉ đánh giá performance từ walk-forward net-cost và trade ledger.
5. Xem Portfolio Backtest để phát hiện shared-leg concentration.
6. Với live entry, hoàn tất mọi execution verification; ticket chỉ là research artifact có thời hạn.

Code chính:

- `tools/pairs_trading/quant/cointegration.py`
- `tools/pairs_trading/quant/engine.py`
- `tools/pairs_trading/quant/backtest.py`
- `tools/pairs_trading/quant/data.py`
- `tools/pairs_trading/quant/portfolio.py`
- `tools/pairs_trading/page.py`
