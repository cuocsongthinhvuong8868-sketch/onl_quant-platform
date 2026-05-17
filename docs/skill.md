# Skill Log — Quant Platform (Continuity Context)

Updated: **2026-05-17**
Mục đích: nén ngữ cảnh để resume công việc instant khi reopen.

---

## 1. Mục tiêu & Posture

Refactor 10+ tools quant rời rạc thành nền tảng Streamlit chuẩn hoá theo skeleton:
- Tách rõ `quant` (business logic, không Streamlit) / `ui` (chart, sidebar) / `page` (render glue)
- Data pipeline kiểu `data_lake/`: app **đọc** CSV; updater scripts **gọi** API
- AI CIO synthesis: 9 tool quant → 1 executive summary qua Kimi/DeepSeek
- Backtest pipeline isolated (look-ahead-free) khỏi live paths

---

## 2. Cấu trúc thư mục

```
app.py                  — Home (3 nhánh, AI CIO panel, PDF export, GitHub sync)
config.py               — paths + AI_PROVIDER_MAP (Kimi + DeepSeek)
tickers.csv             — universe chính, single source of truth (~250 mã)
data_lake/              — market_data, market_volume, vnindex/vn30 cache, bank_fundamentals, fed_liquidity_cache
data_lake/daily_cache/  — pkl (compute) + txt (AI text reports)
pages/
  A_Macro_Analysis.py        — Fed Liquidity
  B_Micro_Analysis.py        — 🚧 đang phát triển
  C_Behavioral_Finance.py    — 9 tools dạng grid menu
  tools_page_C/...           — entry ẩn (gọi tools.<name>.page.render())
tools/<tool>/
  quant/<metrics|engine|...>.py — business logic
  ui/<charts|sidebar>.py
  page.py     — render/show entry
  report.py   — snapshot dict cho AI CIO + machine report
shared/
  data_loader.py    — load_close_prices, load_volumes, load_custom
  daily_cache.py    — get_cache_path, clear_daily_cache, load/save_daily_cache (hash-based pkl)
  ai_cio.py         — 9× run_<tool>() + run_executive_summary()
  github_sync.py    — REST upload + render_sync_button(label, help_text, ...)
  api_key_helper.py — 4-digit shortcut → Streamlit Secrets
  history_selector.py — date+model picker cho AI text history
  page_layout.py    — setup_page()
promt/              — 11 prompt templates (Vietnamese, tên file có space)
command/
  update_data.py             — fetch close+volume (vnstock), save market_data + market_volume
  update_bank_fundamentals.py
  update_fed_liquidity.py    — FRED API
  run_ai_cio_auto.py         — cron GitHub Actions (3:00 AM VN)
  generate_report.py / generate_visual_report.py
.github/workflows/
  update_pipeline.yml        — daily price update
  ai_cio_daily.yml           — AI CIO cron
  fed_liquidity_weekly.yml
```

---

## 3. 10 Tools — Snapshot

| # | Tool | Module | Key logic | AI prompt |
|---|---|---|---|---|
| 1 | Fear & Greed | `fear_greed` | PCA market factor + **EGARCH→GARCH→EWMA fallback** + Kelly skewness | `fear greed promt.md` |
| 2 | Upside/Downside Ratio | `upside_ratio` | Hybrid Logit-AR + Beta-AR Monte Carlo, 5000 sims | `upside ratio promt.md` |
| 3 | Risk-Adjusted Growth | `risk_adjusted_growth` | Disciplined Return + Economic Alpha (banks), P/B unit constant `PRICE_THOUSANDS_TO_VND=1000` | `risk adjusted growth promt.md` |
| 4 | Market Breadth | `market_breadth` | % stocks > MA20/60/125/252 | `Market Breadth promt.md` |
| 5 | ESR Monitor | `esr_monitor` | 5-pillar SSI: S_VOL, S_PRES, S_COR, **S_LIQ=Volume Dry-Up**, S_VAL → PCA(1) rank → HMM regime → 4-state market | `ESR monitor promt.md` |
| 6 | Dispersion | `dispersion` | CSAD/CSSD + DPI + Ledoit-Wolf rolling corr | `dispersion promt.md` |
| 7 | Manipulation | `manipulation` | PCA composite VIC/VHM/VRE vs VN30F1M, percentile rank, 5-regime event study | `manipulation promt.md` |
| 8 | VaRES | `va_res` | Cornish-Fisher VaR/ES, Module B (Contagion VN30) + Module C (Complacency self-baseline) | `va_res_promt.md` |
| 9 | Var-CVaR VNINDEX | `var_cvar_vnindex` | Gaussian + Historical 95% + **EVT POT-GPD** (95/99/99.5) + Hill index, numba kernels | `var_cvar_vnindex_promt.md` |
| 10 | Fed Liquidity (Macro) | `fed_liquidity` | WALCL − TGA − RRP, EMA(4), Z-score 52W → ADD/CUT/HOLD | `fed_liquidity_promt.md` |

**PRODUCTION_REGIME_METHOD** (`tools/esr_monitor/quant/metrics.py:51`) = `'hmm'` cho live paths (ESR Monitor LIVE, AI CIO Manual/AUTO, report snapshot). Backtest dùng `'hmm_walk_forward'` riêng để look-ahead-free.

---

## 4. Data Pipeline

| File | Updater | Mode | Tần suất |
|---|---|---|---|
| `market_data.csv` (close) | `command/update_data.py` | Smart incremental (`combine_first`), backfill `--backfill 2190` | Daily 14:30 VN (GH Actions) |
| `market_volume.csv` (volume) | Same | Same — KHÔNG ffill (NaN giữ ý nghĩa "không giao dịch") | Daily |
| `vnindex_cache.csv` (close + VNINDEX_volume) | Same — `update_vnindex()` | Same | Daily |
| `vn30_cache.csv` (close + VN30_volume) | Same — `update_vn30()` | Same | Daily |
| `bank_fundamentals.csv` | `update_bank_fundamentals.py` | API KBS, fallback cache cũ | Quarterly |
| `dividend_cache.csv` | static | — | Manual |
| `fed_liquidity_cache.csv` | `update_fed_liquidity.py` (FRED API) | Weekly Wed | Weekly |

**Conventions:**
- Universe = `tickers.csv` (single source of truth, ~250 mã). Tool subset phải lọc từ universe chung, không hardcode list riêng.
- `data_lake/` đẩy lên GitHub để Streamlit Cloud chạy ngay (đã ignore `__pycache__`, `.env`, `.streamlit/secrets.toml`).
- Sources: VCI ưu tiên → KBS fallback.

---

## 5. Cache & AI CIO

**Compute cache (`.pkl`)** — `shared/daily_cache.py`:
- Hash-based: `data_lake/daily_cache/<tool>_<hash16>.pkl`
- Key = dict(cấu hình + `s_liq_method`, `real_vol` flags để invalidate khi đổi methodology)
- API: `load_daily_cache`, `save_daily_cache`, `get_cache_path`, `clear_daily_cache`

**AI text cache (`.txt`)** — `shared/ai_cio.py`:
- Date+provider-based: `<tool>_<provider>_<ddmmyy>.txt`
- Helpers: `_read_cache`, `_write_cache`, `_clear_all_tool_caches`, `_read_recent_summaries`

**AI CIO pipeline** (`run_executive_summary`):
1. `_clear_all_tool_caches(provider)` nếu `force=True`
2. Chạy lần lượt 9 `run_<tool>()` — mỗi hàm load data, fill prompt, gọi OpenAI API, cache text
3. `_read_recent_summaries(provider, n_past=2)` — đọc T-1, T-2 (lùi tối đa 7 ngày lịch)
4. Aggregate vào master prompt + gọi 1 lần cuối → trả về executive summary
5. Cron job: `command/run_ai_cio_auto.py` mỗi 14:45 VN (Mon-Fri), DeepSeek, parse `final score & regime` → push Telegram + commit cache lên GitHub

**Multi-provider** (`config.py:AI_PROVIDER_MAP`):
- `kimi-2.6` → `https://api.moonshot.ai/v1` (temp 1.0)
- `deepseek-v4-pro` → `https://api.deepseek.com/v1` (temp 0.5)

**API key shortcut** (`shared/api_key_helper.py`): user gõ 4 số → lookup `AI_KEY_<NNNN>` trong Streamlit Secrets.

**GitHub sync** (`shared/github_sync.py`): `render_sync_button(path, label, help_text, ...)` đẩy file qua REST API. Cần `GITHUB_TOKEN` trong env hoặc Streamlit Secrets.

---

## 6. Conventions khi thêm tool mới

1. Tạo `tools/<name>/{quant,ui}/__init__.py` + `quant/metrics.py` + `ui/charts.py` + `page.py`
2. Entry `pages/tools_page_<branch>/_N_<Name>.py` chỉ gọi `tools.<name>.page.render()`
3. Đăng ký vào `pages/<X>_<Branch>.py:TOOLS` list (id, name, desc, page_module, render_func)
4. Optional: `tools/<name>/report.py` với `snapshot(...)` → AI CIO + machine CSV report tự discovery
5. Optional: `promt/<name>_promt.md` — theo framework prompt v2 (xem §8)
6. Quant layer **không** import Streamlit; UI layer **không** chứa business logic
7. Cache hash phải bao gồm `s_<feature>_method: "vN"` khi đổi methodology để auto-invalidate

---

## 7. Lệnh vận hành nhanh

```bash
# Chạy app
streamlit run app.py

# Update data daily (incremental, ~5 min cho 250 mã)
python command/update_data.py

# Backfill 6 năm (cần khi đổi schema, vd. thêm volume)
python command/update_data.py --backfill 2190

# Update fundamentals (quarterly)
python command/update_bank_fundamentals.py

# Update Fed liquidity (weekly Wed)
python command/update_fed_liquidity.py

# Generate AI CIO manual (forced refresh)
python command/run_ai_cio_auto.py --force
```

---

## 8. Prompt Framework v2 (2026-05-17)

Mọi prompt trong `promt/` theo cùng cấu trúc:

```
PERSONA (1-2 dòng, no priming adjectives — KHÔNG "sắc bén/dứt khoát")
INPUT (placeholders giữ y nguyên format cũ để ai_cio.py compat)
REFERENCE (thresholds + taxonomy)
OUTPUT (Markdown, ~250-400 từ):
  1. Observations (chỉ data, no interpretation)
  2. Interpretation (data → regime, 1-2 câu)
  3. Cross-Check (tìm divergence; "NO ACTIONABLE SIGNAL" nếu mâu thuẫn)
  4. Verdict (action HOẶC explicit no-action)
  5. Structured Tail (JSON cho downstream parsing)
RULES (anti-priming, uncertainty exits)
```

**Executive Summary master**:
- Tail-risk OVERRIDE: ESR Critical (SSI>0.8) HOẶC EVT ξ>0.30 → cap equity ≤30% bất kể score
- Confidence haircut: ≥3/9 tools confidence=low → giảm 1 bracket equity
- Capital Allocation Matrix revised: KHÔNG còn cho Margin ở Score 80+ với vol thấp (bull top trap pattern)
- Last line BẮT BUỘC format: `final score & regime : <0-100> ; regime : <label>`

85/85 placeholders trong 11 prompts match với `ai_cio.py` — không cần đổi Python code.

---

## 9. Recent Sessions (compressed)

### 2026-05-10 — Multi-Provider + GitHub Sync + Workflow
- Thêm DeepSeek vào `AI_PROVIDER_MAP`; UI dropdown chọn provider trong AI CIO + 9 tool con
- GitHub Sync button từ Streamlit Cloud (REST `contents` API, base64 encode)
- `.github/workflows/ai_cio_daily.yml` cron 14:45 VN (07:45 UTC) Mon-Fri, push cache + PDF + send Telegram
- Smart Incremental update_data: `combine_first()` thay vì `.loc[col]=` (silently drop)

### 2026-05-11 — ESR 5-Pillar Full + API Shortcut
- ESR Monitor refactor: từ 3-pillar proxy → 5-pillar SSI (S_VOL, S_PRES, S_COR, S_LIQ, S_VAL)
- Expanding PCA(1) on rank-transformed pillars, sign-aligned with anchor S_VOL
- HMM regime classifier + 4-state market (HEALTHY, EUPHORIC_RISK, CALM_CORRECTION, ACTIVE_STRESS)
- API key shortcut: 4-digit → Streamlit Secrets `AI_KEY_NNNN`

### 2026-05-14 — Fed Liquidity (Nhánh A Macro)
- Port từ Desktop fed dashboard → `tools/fed_liquidity/`
- FRED API pull WALCL/WTREGEN/RRPONTSYD, Net Liquidity = WALCL - TGA - RRP
- Z-score 52W + Impulse EMA(4) → ADD/CUT/HOLD signal
- Pattern app-đọc-cache: `update_fed_liquidity.py` updater, page không gọi FRED trực tiếp

### 2026-05-15 — Backtest Engine + HMM Walk-Forward + History UX
- Backtest module: composite signal (F&G + Breadth + SSI greed + VaR/ES) → logistic equity curve + ESR 4-state overlay + MA200 hard cap
- HMM look-ahead fix: thêm `fit_predict_walk_forward()` (refit mỗi 60d, look-ahead-free)
- 3-period test: Sharpe combined 0.87 vs B&H 0.76 trên 5.8 năm, MaxDD better 12.4pt
- PRODUCTION_REGIME_METHOD constant (`tools/esr_monitor/quant/metrics.py:51`) — single source of truth cho live paths
- History UX: `shared/history_selector.py` chuẩn hoá date+model picker

### 2026-05-17 — Code Review + EVT + Prompt v2 ⭐ CURRENT SESSION

**1. Code Review toàn diện** (góc DS + SWE):
- 14 quant modules audit + 6 shared/command modules
- Phát hiện 2 critical bugs: ESR fake volume (S_PRES + S_LIQ = giả) + P/B unit ambiguity
- 11 medium issues + 60+ broad `except Exception`, code duplication `_create_pdf` 2 chỗ

**2. Fix A2 — P/B unit constant** (`tools/risk_adjusted_growth/quant/data_prep.py`):
- Extract `PRICE_THOUSANDS_TO_VND=1000`, `CASH_PAYOUT_CAP=0.5`, `BVPS_UNIT_SANITY_FLOOR=1000`
- Logger warning khi BVPS<1000 (nghi sai unit)

**3. Fix A8 — Numba VaR ES** (`tools/var_cvar_vnindex/quant/metrics.py`):
- `@njit(fastmath=True, cache=True)` kernel cho `_rolling_es_kernel`
- Parity với pandas cũ: diff < 1e-17

**4. Fix A5 — EGARCH fallback chain** (`tools/fear_greed/quant/volatility.py`):
- EGARCH Skewed-T → GARCH(1,1) Gaussian → EWMA λ=0.94
- Check `convergence_flag` thay try/except blind, log tier nào fire
- AI CIO không còn crash khi EGARCH fail

**5. Fix A1 — ESR Monitor real volume**:
- `config.py`: thêm `MARKET_VOLUME` path
- `command/update_data.py`: tách `fetch_history()` trả `[close, volume]`; fetch_close giữ backwards-compat
- `shared/data_loader.py`: `load_volumes()` graceful (None nếu file thiếu)
- `tools/esr_monitor/quant/metrics.py:run_esr_pipeline`: thêm `df_volume` param, detect `VN30_volume`, fallback có warning rõ
- 5 callers updated: ai_cio, esr page, esr report, backtest page + composite_signal

**6. S_LIQ regression discovery + fix** (sau khi user feedback):
- Amihud illiquidity trên VN30 bluechip: Spearman với S_VOL = +0.008 (không correlate stress)
- Hệ thống cũ "đẹp mắt" vì fake volume biến Amihud thành |ret|/close ≈ duplicate S_VOL (Spearman +0.49)
- **REPLACE methodology**: S_LIQ = `-log(MA20(daily_dollar_vol) / MA252(daily_dollar_vol))` = Volume Dry-Up
- Verified: S_LIQ percentile rank ngày 15/05 = 79% (khớp user intuition "thanh khoản kém"); SSI 63.4% downside mode, S_LIQ là driver chính weight 0.36
- Bump `s_liq_method: "volume_dryup_v1"` vào cache key → auto-invalidate

**7. EVT POT-GPD** (`tools/var_cvar_vnindex/quant/evt.py` — 220 dòng mới):
- `pot_threshold`, `fit_gpd` (scipy MLE), `evt_var`, `evt_es`, `hill_estimator`, `rolling_evt_metrics`
- Refit mỗi 21 phiên (~21× speedup, accuracy loss <1%)
- 0.53s compute cho 2608 ngày
- Snapshot 15/05/2026 VN-Index: ξ=0.346 (fat tail), Hill=0.471, EVT VaR 99%=-3.66% vs Gaussian -2.70% → Gaussian underestimate 1pp
- UI: tab "🔥 EVT Tail Risk" với 2 subplot (VaR/ES + ξ/Hill), reference lines 0.15/0.30
- 8 EVT metric cards + diagnostic banner so sánh Gaussian gap
- `report.py` snapshot bổ sung 12 EVT fields; AI CIO + prompt template updated

**8. ESR rerun + GitHub sync buttons** (`tools/esr_monitor/page.py`):
- Session_state flag + `clear_daily_cache()` → "🔄 Chạy lại Model"
- `render_sync_button(label="📤 Cập nhật cache Model lên GitHub", ...)` cho file .pkl
- `shared/github_sync.py:render_sync_button` mở rộng nhận `label`, `help_text`, `use_container_width` (backwards-compat default)
- `shared/daily_cache.py`: thêm `get_cache_path()` (public alias) + `clear_daily_cache()`
- Fix `UnboundLocalError`: xoá inline import `from shared.github_sync import render_sync_button` ở line 319 (conflict với top-level import)

**9. Prompts v2 redesign — 11 files**:
- Framework: PERSONA + Observations → Interpretation → Cross-Check → Verdict + JSON tail
- Bỏ math LaTeX redundant, fix stale refs (S_LEV→S_PRES, Amihud→Volume Dry-Up trong ESR)
- Anti-priming: bỏ "sắc bén", "dứt khoát", "kỷ luật sắt đá"
- "NO ACTIONABLE SIGNAL" valid khi data mâu thuẫn
- Executive Summary master: tail-risk override + confidence haircut + KHÔNG cho margin Score>80 vol thấp
- 85/85 placeholders match `ai_cio.py`

**10. Aggressive mode** (`.claude/settings.local.json`):
- `"defaultMode": "bypassPermissions"` cho repo này (project-scoped, không leak user-level)
- Allowlist mở rộng: `python3 *`, `pip *`, `grep *`, `git *`, `streamlit *`, etc.

---

## 10. Known Issues & Roadmap

**Issues còn lại (từ Code Review §1 chưa fix):**
- `shared/ai_cio.py` 594 dòng — God module, recommend refactor sang registry pattern
- 61 instances `except Exception` rộng → mất stacktrace khi prod fail
- Cache key dùng `date.today()` thay vì `df_stocks.index[-1]` → bug timezone Streamlit Cloud (UTC) vs VN (UTC+7)
- Thư mục `promt/` (typo) — không rename vì hardcoded paths khắp ai_cio.py
- Hardcoded `t0_dt = pd.to_datetime("2026-03-02")` trong manipulation
- `_create_pdf` duplicate ở `app.py:193` và `command/run_ai_cio_auto.py:79`
- Workflow `update_pipeline.yml` còn `MY_API_KEY` dead code + `git add .` risk

**Roadmap đề xuất (theo Tier A khả thi ngay):**
1. ✅ EVT POT-GPD (xong session này)
2. ⏭️ Multi-factor Risk Model (Barra-lite): style factors Value/Size/Mom/Quality/LowVol + industry decomposition
3. ⏭️ MES / SRISK (NYU V-Lab pattern): systemic contribution từng VN30 mã
4. ⏭️ Diebold-Yilmaz Spillover Index: VAR + FEVD network analysis
5. ⏭️ DCC-GARCH: dynamic correlation matrix (thay Ledoit-Wolf static)
6. ⏭️ HRP (Hierarchical Risk Parity): thay logistic curve trong backtest allocation
7. ⏭️ Deflated Sharpe / Probabilistic Sharpe — bảo vệ credibility backtest

**Tier B (cần data extra):**
- VPIN microstructure (cần intraday tick data)
- News sentiment NLP (PhoBERT + scrape VnExpress/CafeF)
- Foreign flow analytics (cần API HSC/SSI/FireAnt)
- VN30F1M positioning + Open Interest

---

## 11. Quick Reference

**Production constants:**
- `tools/esr_monitor/quant/metrics.py:51` → `PRODUCTION_REGIME_METHOD = 'hmm'`
- `tools/risk_adjusted_growth/quant/data_prep.py` → `PRICE_THOUSANDS_TO_VND = 1000`
- `tools/var_cvar_vnindex/quant/evt.py` → `DEFAULT_REFIT_EVERY = 21`, `DEFAULT_THRESHOLD_PCT = 0.10`
- `tools/fear_greed/quant/volatility.py` → `EWMA_LAMBDA = 0.94` (fallback)

**Universe & data:**
- ~250 tickers trong `tickers.csv`, VN30 hardcoded `VN30_TICKERS` (30 mã) trong `tools/esr_monitor/quant/metrics.py:36`
- VNINDEX → riêng `vnindex_cache.csv`; VN30 → `vn30_cache.csv`
- VN30F1M futures → trong `market_data.csv` (dùng cho Manipulation tool)

**Performance benchmarks (5.8y):**
- Backtest Sharpe: 0.87 (vs B&H 0.76)
- MaxDD: -23.7% (vs B&H -40.3%)
- CAGR: 10.84% (vs B&H 15.05%) — defensive long-only trade-off

**Verification status (sau session 2026-05-17):**
- 12/12 file thay đổi compile sạch
- EVT smoke test: 1.31s cho 2608 ngày (full pipeline classic+EVT)
- Numba kernel parity với pandas cũ: 6.94e-18 max diff
- 85/85 prompt placeholders match `ai_cio.py`
- ESR pipeline both paths (real volume + fallback): SSI differ 0.4567 vs 0.4225 → confirm volume thật ảnh hưởng output
