# Skill Log — Quant Platform (Continuity Context)

**Updated:** 2026-05-19 (GFCM ship)
**Purpose:** nén ngữ cảnh để resume công việc instant khi reopen.

---

## 1. Mục tiêu & Posture

Streamlit-based quant platform cho thị trường VN, kiến trúc 3-tier:
- `quant` (business logic, **không** Streamlit) / `ui` (chart, sidebar) / `page` (render glue)
- Data pipeline `data_lake/`: app **đọc** CSV; updater scripts **gọi** API
- AI CIO synthesis: 9 VN-equity tool → 1 executive summary qua Kimi/DeepSeek
- Backtest pipeline isolated (look-ahead-free) khỏi live paths
- Macro tools (Fed Liquidity, GFCM) **đứng riêng** — AI analysis trên page, KHÔNG inject executive summary

---

## 2. Cấu trúc thư mục

```
app.py                  — Home (3 nhánh, AI CIO panel, PDF export, GitHub sync)
config.py               — paths + AI_PROVIDER_MAP (Kimi + DeepSeek)
tickers.csv             — universe chính, single source of truth (~250 mã)
data_lake/              — market_data, market_volume, vnindex/vn30, fundamentals,
                          fed_liquidity_cache, global_financial_conditions_cache,
                          ticker_metadata, Ai_cio_report
data_lake/daily_cache/  — pkl (compute) + txt (AI text reports)
pages/
  A_Macro_Analysis.py        — Fed Liquidity, GFCM
  B_Micro_Analysis.py        — Pairs Trading
  C_Behavioral_Finance.py    — 9 tools dạng grid menu
  tools_page_{A,B,C}/…       — entry ẩn (gọi tools.<name>.page.render())
tools/<tool>/
  quant/<metrics|engine|...>.py — business logic
  ui/<charts|sidebar>.py
  page.py     — render entry
  report.py   — snapshot dict (chỉ tool nào plug AI CIO mới có)
shared/
  data_loader.py      — load_close_prices, load_volumes, load_custom, load_ticker_metadata
  daily_cache.py      — get_cache_path, clear_daily_cache, load/save_daily_cache (hash-based pkl)
  ai_cio.py           — 9× run_<tool>() + run_executive_summary()
  dcc_garch.py        — fit_dcc, dynamic_correlation_matrix, pair_correlation
  github_sync.py      — REST upload + render_sync_button
  api_key_helper.py   — 4-digit shortcut → Streamlit Secrets
  history_selector.py — date+model picker
  page_layout.py
promt/              — 12 prompt templates (Vietnamese, tên file có space - typo intentional)
command/
  update_data.py                          — vnstock close+volume
  update_bank_fundamentals.py             — KBS fundamentals quarterly
  update_fed_liquidity.py                 — FRED WALCL/TGA/RRP weekly
  update_global_financial_conditions.py   — FRED VIX/HY/CCC + Yahoo MOVE daily
  update_sector_data.py                   — ICB metadata
  run_ai_cio_auto.py                      — cron GH Actions
  generate_report.py / generate_visual_report.py
.github/workflows/
  update_pipeline.yml        — daily price update
  ai_cio_daily.yml           — AI CIO cron 14:45 VN
  fed_liquidity_weekly.yml
```

---

## 3. 11 Tools Active — Snapshot

| # | Branch | Tool | Module | Key tech | AI integration |
|---|---|---|---|---|---|
| 1 | C | Fear & Greed | `fear_greed` | PCA + EGARCH→GARCH→EWMA fallback + Kelly skewness | Executive summary |
| 2 | C | Upside Ratio | `upside_ratio` | Hybrid Logit-AR + Beta-AR Monte Carlo 5000 sims | Executive summary |
| 3 | C | Risk-Adjusted Growth | `risk_adjusted_growth` | Disciplined Return + Economic Alpha (banks) | Executive summary |
| 4 | C | Market Breadth | `market_breadth` | % stocks > MA20/60/125/252 | Executive summary |
| 5 | C | **ESR Monitor** | `esr_monitor` | 5-pillar SSI (S_VOL/S_PRES/S_COR/**S_LIQ=Volume Dry-Up**/S_VAL) + HMM regime | Executive summary |
| 6 | C | Dispersion | `dispersion` | CSAD/CSSD + DPI + Ledoit-Wolf | Executive summary |
| 7 | C | Manipulation | `manipulation` | PCA composite VIC/VHM/VRE vs VN30F1M, percentile regime | Executive summary |
| 8 | C | VaRES | `va_res` | Cornish-Fisher + Self-baseline Complacency | Executive summary |
| 9 | C | **Var-CVaR VNINDEX** | `var_cvar_vnindex` | Gaussian + Historical + **EVT POT-GPD** + Hill | Executive summary |
| 10 | A | Fed Liquidity | `fed_liquidity` | WALCL − TGA − RRP, Z-score 52W → ADD/CUT/HOLD | Standalone (AI tab trên page) |
| 11 | A | **GFCM** | `global_financial_conditions` | VIX + MOVE + HY OAS + CCC OAS, **static PCA**, regime via PC1 percentile 3Y | Standalone (AI tab trên page) |
| 12 | B | **Pairs Trading** | `pairs_trading` | Engle-Granger + Johansen + OU half-life + Z-score 60d | KHÔNG plug AI CIO (orthogonal) |

`PRODUCTION_REGIME_METHOD` (`tools/esr_monitor/quant/metrics.py:51`) = `'hmm'` cho live paths. Backtest dùng `'hmm_walk_forward'` riêng.

---

## 4. Data Pipeline

| File | Updater | Tần suất |
|---|---|---|
| `market_data.csv` (close) | `update_data.py` smart-incremental | Daily 14:30 VN |
| `market_volume.csv` | Same — KHÔNG ffill (NaN giữ nghĩa) | Daily |
| `vnindex_cache.csv` / `vn30_cache.csv` | Same | Daily |
| `bank_fundamentals.csv` | `update_bank_fundamentals.py` (KBS) | Quarterly |
| `ticker_metadata.csv` | `update_sector_data.py` (vnstock Listing) | Quarterly |
| `fed_liquidity_cache.csv` | `update_fed_liquidity.py` (FRED) | Weekly Wed |
| `global_financial_conditions_cache.csv` | `update_global_financial_conditions.py` (FRED + Yahoo) | Daily |

**Conventions**:
- Universe = `tickers.csv` (~250 mã). Tool subset lọc từ universe chung, KHÔNG hardcode list riêng.
- `data_lake/` push lên GitHub để Streamlit Cloud chạy ngay.
- Source priority: VCI > KBS fallback (for VN equity).

---

## 5. Cache & AI CIO

**Compute cache `.pkl`** — `shared/daily_cache.py`:
- Hash-based: `data_lake/daily_cache/<tool>_<hash16>.pkl`
- Key = dict(cấu hình + `s_<feature>_method: "vN"` flags)
- API: `load_daily_cache`, `save_daily_cache`, `get_cache_path`, `clear_daily_cache`

**AI text cache `.txt`** — `shared/ai_cio.py`:
- Date+provider: `<tool>_<provider>_<ddmmyy>.txt`

**AI CIO pipeline** (`run_executive_summary`):
1. `_clear_all_tool_caches(provider)` nếu `force=True`
2. Chạy 9 `run_<tool>()` lần lượt (cache hit nếu cùng ngày)
3. `_read_recent_summaries(provider, n_past=2)` đọc T-1, T-2
4. Aggregate vào master prompt → 1 lần OpenAI call cuối
5. Auto upsert `Ai_cio_report.csv`: same-day overwrite (manual ghi đè auto), T+1 append
6. Cron `run_ai_cio_auto.py` 14:45 VN (Mon-Fri), DeepSeek, push Telegram + commit cache

**Multi-provider** (`config.AI_PROVIDER_MAP`): `kimi-2.6` (Moonshot, temp 1.0) / `deepseek-v4-pro` (temp 0.5)

**API key shortcut** (`api_key_helper.py`): user gõ 4 số → lookup `AI_KEY_<NNNN>` trong Streamlit Secrets.

**GitHub sync** (`github_sync.py`): `render_sync_button(path, label, help_text, ...)` đẩy file qua REST. Cần `GITHUB_TOKEN`.

---

## 6. Conventions khi thêm tool mới

1. Tạo `tools/<name>/{quant,ui}/__init__.py` + `quant/metrics.py` + `ui/charts.py` + `ui/sidebar.py` + `page.py`
2. Entry `pages/tools_page_<branch>/_N_<Name>.py` chỉ gọi `tools.<name>.page.render()`
3. Đăng ký vào `pages/<X>_<Branch>.py:TOOLS` list (id, name, desc, page_module, render_func)
4. **Optional**: `tools/<name>/report.py` snapshot() — chỉ cần nếu plug AI CIO executive summary
5. **Optional**: `promt/<name>_promt.md` — framework prompt v2 (§8)
6. Quant layer **không** import Streamlit; UI **không** chứa business logic
7. Errors trong quant → RAISE; UI catch + log
8. Cache hash phải bao gồm `s_<feature>_method: "vN"` khi đổi methodology
9. **Macro / cross-asset / non-VN-equity tool**: theo precedent `fed_liquidity`/`gfcm` — AI tab riêng trên page, KHÔNG inject executive summary aggregator (giữ scope sạch — executive summary là cho 9 VN-equity tools)

---

## 7. Commands

```bash
# App
streamlit run app.py

# Data update
python command/update_data.py                          # daily incremental ~5 min
python command/update_data.py --backfill 2190          # 6 năm backfill
python command/update_bank_fundamentals.py             # quarterly
python command/update_fed_liquidity.py                 # weekly Wed (FRED)
python command/update_global_financial_conditions.py   # daily (FRED+Yahoo)
python command/update_sector_data.py                   # quarterly ICB

# AI CIO
python command/run_ai_cio_auto.py --force              # manual refresh
```

---

## 8. Prompt Framework v2

```
PERSONA (1-2 dòng, no priming adjectives)
INPUT (placeholders giữ format cũ — ai_cio.py .replace() literal)
REFERENCE (thresholds + taxonomy)
OUTPUT (Markdown, ~250-500 từ):
  1. Observations (data only)
  2. Interpretation (data → regime, 1-2 câu)
  3. Cross-Check (divergence; "NO ACTIONABLE SIGNAL" nếu mâu thuẫn)
  4. Verdict (action HOẶC explicit no-action)
  5. JSON tail cho downstream parsing
RULES (anti-priming, anti-hallucination, no absolute VN stock prices)
```

**Executive Summary master rules**:
- Tail-risk OVERRIDE: ESR Critical (SSI>0.8) HOẶC EVT ξ>0.30 → cap equity ≤ 30%
- Confidence haircut: ≥ 3/9 tools confidence=low → giảm 1 bracket equity
- KHÔNG margin ở Score 80+ với vol thấp (bull top trap)
- Last line BẮT BUỘC: `final score & regime : <0-100> ; regime : <label>`

**Anti-hallucination prices**: cấm mức giá tuyệt đối VN stock ở 6 prompts. Manipulation prompt inject real-time `{vic_close}` `{vhm_close}` `{vre_close}` `{f1m_close}` từ `df_prices.iloc[-1]`.

---

## 9. Recent Sessions (compressed)

### Pre-2026-05 (highlights — full log archived)
- **2026-05-10**: Multi-provider (Kimi + DeepSeek) + GitHub sync + GH Actions daily cron
- **2026-05-11**: ESR 5-pillar SSI + HMM 4-state regime + API key shortcut
- **2026-05-14**: Fed Liquidity tool (FRED) — nhánh A first
- **2026-05-15**: Backtest engine + HMM walk-forward + history UX

### 2026-05-17 — Code Review + EVT + Prompt v2
- 14 quant modules audit; fix P/B unit ambiguity + ESR fake-volume + EGARCH fallback chain
- **S_LIQ replaced**: Amihud → Volume Dry-Up (`-log(MA20/MA252 dollar vol)`) — Amihud không correlate stress trên VN30 bluechip
- **EVT POT-GPD** (`tools/var_cvar_vnindex/quant/evt.py`, 220 LOC): refit mỗi 21 phiên, ξ=0.346 trên VN-Index 15/05/26 (fat tail)
- **Prompt v2** redesign 11 files — 85/85 placeholders compat
- **Anti-hallucination prices** rules — 6 prompts
- **Module resolution** fix: xóa `command/config.py` shim + add `__init__.py` 3 packages
- **Claude CLI** install + `CLAUDE.md` auto-load + `Run_Claude.command` Mac launcher
- **Aggressive mode**: `.claude/settings.local.json` bypassPermissions với gate `skipDangerousModePermissionPrompt` ở root

### 2026-05-18 — Pairs Trading Spec + Manipulation t0 fix
- Build spec §13 (Pairs Trading) + §12 (Factor Risk Model) drafted
- Fix manipulation hardcoded `t0_dt` → dynamic `result_df.index[-60]`

### 2026-05-19 — Pairs Trading SHIP + GFCM SHIP

**Pairs Trading Lab (§13)** — shipped PR #2 (merged):
- `tools/pairs_trading/` 7 files, ~1421 LOC
- `quant/cointegration.py`: `engle_granger()`, `johansen_test()`, `ou_half_life()`, `hurst()`, `pairwise_eg_matrix()`
- `quant/signal.py`: FSM long/short/flat, time-stop 2× half-life, quarantine on |z|>3
- `quant/backtest.py`: basket_pnl, transaction cost model, summary stats, order ticket
- `quant/clusters.py`: 7 PREDEFINED clusters (Vingroup, Big4_Bank, Steel, Securities, Private_Bank, Oil_Gas, Utility)
- `page.py` 5 tabs: Cluster Scan / Pairwise Heatmap / Custom Pair / Aggregate Backtest / Live Signals
- KHÔNG plug AI CIO (orthogonal signal — per-pair discrete, time-sensitive)
- **Sector ingestion bonus**: `command/update_sector_data.py` + `data_lake/ticker_metadata.csv` (245/253 covered)
- **DCC-GARCH utility** (`shared/dcc_garch.py`, 513 LOC) — placed shared, chưa wire vào pairs filter (defer cho V2)
- Real-data smoke: VIC/VHM EG p=0.004, β=1.65; Big4_Bank Johansen pass; Vingroup 3-way 1 cointegration relation (VRE pair fails 95% → in-page warning)

**Global Financial Conditions Monitor (GFCM)** — shipped PR #6 (merged):
- `tools/global_financial_conditions/` 9 files, ~1399 LOC
- 4 indicators: VIX (FRED `VIXCLS`), MOVE (Yahoo `^MOVE`), HY OAS (FRED `BAMLH0A0HYM2`), CCC OAS (FRED `BAMLH0A3HYC`) + derived Credit Quality Spread (CCC − HY)
- **Static PCA** trên rolling z-score 252d (1Y — FRED ICE BofA chỉ cấp ~3Y history): PC1 = stress factor (VIX-anchored sign), PC2 = divergence (HY-anchored)
- Regime via PC1 rolling percentile 1Y: STRESS (≥80%) / ELEVATED (50-80%) / CALM (<50%)
- Driver flag: EQUITY_DRIVEN / RATES_DRIVEN / HY_CREDIT_DRIVEN / CCC_CREDIT_DRIVEN / BROAD_STRESS (≥3/4 ≥80pct) / NO_STRESS
- 2-tab page: **📊 Level** (4-panel raw + mean overlay) / **🧠 Analytics** (PC1+regime band, percentile small multiples, PC2-vs-PC1 scatter, CQS chart, AI section)
- Sidebar: slider "Lùi bao nhiêu năm?" (1-22, default 3) — chỉ filter display, PCA fit + percentile vẫn dùng full history
- Standalone AI tab (giống fed_liquidity pattern), KHÔNG inject executive summary
- History từ 2003 (limit của MOVE Yahoo coverage)
- Smoke test: PCA loadings + explained variance valid, regime distribution reasonable
- Requirements: thêm `yfinance>=0.2.40`

---

## 10. Known Issues & Roadmap

**Open issues (đang track):**
- `shared/ai_cio.py` 700+ dòng — God module, recommend refactor sang registry pattern (thêm tool mới hay phải edit list `tool_names` trong `_clear_all_tool_caches`)
- 61 instances `except Exception` rộng — mất stacktrace prod fail
- Cache key dùng `date.today()` — timezone bug Streamlit Cloud (UTC) vs VN (UTC+7) → đổi sang `df_stocks.index[-1]`
- `_create_pdf` duplicate ở `app.py:193` và `command/run_ai_cio_auto.py:79` → extract `shared/pdf_export.py`
- DCC-GARCH chưa có parity test runtime trên full 50-ticker × 2500-obs
- Pairs Trading chưa wire DCC filter (defer V2)
- Pairs Aggregate Backtest tab chưa stress-test cluster 6-way → có thể timeout Cloud
- `promt/` typo — không rename vì hardcoded paths khắp `ai_cio.py`

**Roadmap còn lại:**
| # | Item | Status | Blocker |
|---|---|---|---|
| §12 | **Factor Risk Model** (Barra-VN lite, 6 style + ~10 industry, cross-sectional WLS) | 🚧 PROPOSED, chưa code | vnstock free Community = 8 quý BCTC → backtest 5+ năm cần Sponsor paid. P1 (3-factor không cần BCTC) ship được ngay |
| #3 | MES / SRISK (NYU V-Lab) | 📋 idea | — |
| #4 | Diebold-Yilmaz Spillover (VAR + FEVD) | 📋 idea | — |
| #6 | HRP (Hierarchical Risk Parity) thay logistic backtest curve | 📋 idea | — |
| #7 | Deflated Sharpe / PSR | 📋 idea | — |

**Tier B (cần data extra):**
- VPIN microstructure (intraday tick)
- News sentiment NLP (PhoBERT + scrape)
- Foreign flow analytics (HSC/SSI API)
- VN30F1M positioning + Open Interest

---

## 11. Quick Reference

**Production constants:**
- `tools/esr_monitor/quant/metrics.py:51` → `PRODUCTION_REGIME_METHOD = 'hmm'`
- `tools/risk_adjusted_growth/quant/data_prep.py` → `PRICE_THOUSANDS_TO_VND = 1000`
- `tools/var_cvar_vnindex/quant/evt.py` → `DEFAULT_REFIT_EVERY = 21`
- `tools/fear_greed/quant/volatility.py` → `EWMA_LAMBDA = 0.94` (fallback)
- `tools/global_financial_conditions/quant/metrics.py` → `ROLLING_WINDOW = 252` (1Y — FRED ICE BofA truncate), `PCT_STRESS = 0.80`, `START_DATE = "2003-01-01"`

**Universe & data:**
- ~250 tickers `tickers.csv`; VN30 hardcoded `VN30_TICKERS` (30 mã) trong `tools/esr_monitor/quant/metrics.py:36`
- VN30F1M futures trong `market_data.csv` (Manipulation tool)

**Performance benchmarks (5.8y backtest):**
- Sharpe combined 0.87 (vs B&H 0.76), MaxDD -23.7% (vs B&H -40.3%), CAGR 10.84% (defensive long-only)

**Workflow resume:**
1. `cd ~/Documents/GitHub/onl_quant-platform` HOẶC double-click `Run_Claude.command`
2. Claude CLI tự load `CLAUDE.md` + `.claude/settings.local.json` (bypass mode)
3. Đọc `docs/skill.md` (file này) nếu cần ngữ cảnh sâu
4. Bypass mode active → Bash/Edit không hỏi xác nhận

**Verification helpers:**
- Compile check: `python3 -m py_compile <file>`
- Prompt placeholder compat: grep `\[.*\]` trong prompt vs `.replace("...")` trong `ai_cio.py` / page.py
- Numba kernel parity: pandas equivalent diff < 1e-15 (xem `_rolling_es_kernel` pattern)

**Anti-pattern reminders (đã học):**
- ❌ KHÔNG cho Margin khi Score>80 vol thấp (bull top trap)
- ❌ KHÔNG đưa mức giá tuyệt đối VN stock trong AI report (training data cũ 2-3 năm)
- ❌ KHÔNG dùng Amihud illiquidity cho VN30 bluechip (không correlate stress) — dùng Volume Dry-Up
- ❌ KHÔNG `except Exception` rộng (silently swallow) — quant phải raise; UI mới catch
- ❌ KHÔNG hardcode list trong `_clear_all_tool_caches` — thêm tool mới sẽ quên
- ❌ KHÔNG tạo `command/config.py` shim — Python module collision với root
- ❌ KHÔNG inject macro/cross-asset tool vào executive summary aggregator (dilute scope) — theo pattern fed_liquidity / GFCM
