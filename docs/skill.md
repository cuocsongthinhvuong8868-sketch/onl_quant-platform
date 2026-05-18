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
- **Gate fix**: `bypassPermissions` cần `skipDangerousModePermissionPrompt: true` + `skipAutoPermissionPrompt: true` ở **ROOT level** (KHÔNG inside `permissions`) — thiếu gate này thì Claude silently fallback default mode mà không báo lỗi.

**11. AI CIO history CSV — unified upsert** (`shared/ai_cio.py`):
- Move `parse_score_regime` + `upsert_history_csv` từ `run_ai_cio_auto.py` → `shared/ai_cio.py`; `run_executive_summary(source="manual"|"auto")` TỰ ĐỘNG upsert CSV
- **Same-day overwrite**: manual ghi đè auto cùng ngày (user trust > cron); T+1 thì append
- CSV schema mở rộng `ddmmyyyy, score, regime, source, provider` (backwards-compat migrate row cũ)
- History page: badge "🤖 Auto" / "👤 Manual" + provider, stats source distribution. 6/6 tests pass

**12. Anti-hallucination price rules — 6 prompts**:
- Vấn đề: AI ghi "VIC mất 45,000" trong khi VIC thực = 228k (training data cũ 2-3 năm)
- Cấm mức giá tuyệt đối ở: `executive_summary`, `manipulation`, `ESR monitor`, `var_cvar_vnindex`, `va_res`, `risk_adjusted_growth`. Bắt buộc dùng % hoặc technical level (MA, support/resistance). 51/51 placeholders compat preserved

**13. Real-time price injection** (manipulation prompt):
- `run_manipulation` inject 4 placeholders mới `{vic_close}` `{vhm_close}` `{vre_close}` `{f1m_close}` từ `df_prices.iloc[-1]`
- 2 formatters: `_fmt_stock_price` (×1000→VND) vs `_fmt_futures_index` (điểm, no scaling)
- Verify (15/05/2026): VIC=228.00 (≈228,000 VND), VHM=158.00, VRE=34.00, F1M=2,053.90 điểm

**14. Module resolution + Streamlit Cloud KeyError fix**:
- Lỗi `KeyError: 'config'` / `'shared'` khi Cloud rebuild — nguyên nhân: 2 `config.py` (root + `command/`) + thiếu `__init__.py` ở `pages/`, `command/`, `pages/tools_page_C/`
- Fix: xoá `command/config.py` (shim stale thiếu `MARKET_VOLUME`); tạo 3 `__init__.py` package markers; hardening `upload_file()` defensive JSON parse + `render_sync_button()` capture full traceback

**15. Claude CLI + auto-context loading**:
- Cài `@anthropic-ai/claude-code` v2.1.143 qua npm global (Node 22 sẵn qua nvm)
- `CLAUDE.md` (89 dòng) auto-load khi `cd` vào project; `Run_Claude.command` Mac double-click launcher
- Verify: `claude -p` từ project dir tự load context + apply bypass mode

---

## 10. Known Issues & Roadmap

**Issues còn lại (từ Code Review §1 chưa fix):**
- `shared/ai_cio.py` 700+ dòng (đã grow sau session) — God module, recommend refactor sang registry pattern
- 61 instances `except Exception` rộng → mất stacktrace khi prod fail (đã hardening `render_sync_button` để capture traceback)
- Cache key dùng `date.today()` thay vì `df_stocks.index[-1]` → bug timezone Streamlit Cloud (UTC) vs VN (UTC+7)
- Thư mục `promt/` (typo) — không rename vì hardcoded paths khắp ai_cio.py
- ✅ ~~Hardcoded `t0_dt = pd.to_datetime("2026-03-02")` trong manipulation — fix thành rolling 60-phiên gần nhất~~ → FIXED 2026-05-18 (`shared/ai_cio.py:264` dùng `result_df.index[-60]`, mirror UI default `tools/manipulation/page.py:71`)
- `_create_pdf` duplicate ở `app.py:193` và `command/run_ai_cio_auto.py:79`
- Workflow `update_pipeline.yml` còn `MY_API_KEY` dead code + `git add .` risk
- ✅ ~~Duplicate `command/config.py`~~ → FIXED 2026-05-17 (xoá shim + add `__init__.py`)
- ✅ ~~`pages/tools_page_C/__init__.py` thiếu~~ → FIXED 2026-05-17

**Anti-hallucination còn cải tiến được:**
- Hiện chỉ manipulation prompt có inject giá real-time. Có thể mở rộng cho:
  - `risk_adjusted_growth` (bank prices cho stop-loss recommendation)
  - `va_res` (Top Crash list cần kèm giá hiện tại)
  - `executive_summary` master (mọi stock pick phải có giá đối chiếu)
- Pattern: pass `last_prices = df_stocks.iloc[-1]` qua kwargs → format helpers → prompt inject

**Roadmap đề xuất (theo Tier A khả thi ngay):**
1. ✅ EVT POT-GPD (xong session này)
2. 🚧 **CHƯA HOÀN THÀNH** — Multi-factor Risk Model (Barra-lite): style factors Value/Size/Mom/Quality/LowVol + industry decomposition. **Blocker**: vnstock free tier giới hạn BCTC 8 quý (~2 năm) → backtest weak; chờ Sponsor tier hoặc accept Phase 1 (3-factor không cần fundamental). **Build spec đầy đủ ở §12.**
3. ⏭️ MES / SRISK (NYU V-Lab pattern): systemic contribution từng VN30 mã
4. ⏭️ Diebold-Yilmaz Spillover Index: VAR + FEVD network analysis
5. ⏭️ DCC-GARCH: dynamic correlation matrix (thay Ledoit-Wolf static)
6. ⏭️ HRP (Hierarchical Risk Parity): thay logistic curve trong backtest allocation
7. ⏭️ Deflated Sharpe / Probabilistic Sharpe — bảo vệ credibility backtest
8. 🚧 **CHƯA HOÀN THÀNH** — Pairs Trading research lab (Engle-Granger + Johansen + OU half-life). Không plug AI CIO synthesis — đứng độc lập trên nhánh B_Micro_Analysis. **Build spec đầy đủ ở §13.**

**⚠️ Pending Build Backlog (cần track riêng):**
| # | Tool | Trạng thái | Blocker chính |
|---|---|---|---|
| §12 | Factor Risk Model (Barra-VN lite) | 🚧 PROPOSED, chưa code | vnstock free tier BCTC 8 quý → backtest 5+ năm cần Sponsor paid |
| §13 | Pairs Trading research lab | 🚧 PROPOSED, chưa code | Execution gap (T+2, FOL, lot size) — 1-2 tuần MVP nếu prioritize |

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

**Verification status (sau session 2026-05-17 full):**
- Toàn bộ file thay đổi compile sạch (~25 files đụng tới)
- EVT smoke test: 1.31s cho 2608 ngày (full pipeline classic+EVT)
- Numba kernel parity với pandas cũ: 6.94e-18 max diff
- Prompt placeholders compat: 85/85 (initial v2) + 51/51 (sau anti-hallucination) → cùng `ai_cio.py` không vỡ
- ESR pipeline both paths (real volume + fallback): SSI differ 0.4567 vs 0.4225 → confirm volume thật ảnh hưởng output
- AI CIO CSV upsert: 6/6 tests pass (parse, same-day overwrite, T+1 append, invalid reject, backwards-compat migrate)
- Real-time prices (15/05/2026): VIC=228k, VHM=158k, VRE=34k, VN30F1M=2053.9pt
- Claude CLI 2.1.143 verified `claude -p` từ project dir auto-loads CLAUDE.md + bypass mode

**Workflow new for session resume:**
1. `cd ~/Documents/GitHub/onl_quant-platform` HOẶC double-click `Run_Claude.command`
2. Claude CLI tự load `CLAUDE.md` (89 dòng context) + `.claude/settings.local.json` (bypass mode)
3. Đọc `docs/skill.md` nếu cần ngữ cảnh sâu (session history compressed)
4. Bypass mode active → Bash/Edit không hỏi xác nhận

**Files mới của session này:**
- `CLAUDE.md` (89 dòng) — auto-loaded context cho Claude CLI
- `Run_Claude.command` (executable) — Mac launcher
- `tools/var_cvar_vnindex/quant/evt.py` (220 dòng) — POT-GPD core
- `command/__init__.py`, `pages/__init__.py`, `pages/tools_page_C/__init__.py` — package markers

---

## 12. Factor Risk Model — Build Spec (PROPOSED 2026-05-18)

**Posture**: Barra-VN lite — Tier A roadmap #2. Đây là **missing primitive**: 9/10 tool hiện tại đo index/pillar aggregate, không có cách nào decompose stock return → factor exposure + alpha. Branch target: `B_Micro_Analysis` (đang trống).

### 12.1. Factor design — 6 style + ~10 industry

| Factor | Spec | Data | Status |
|---|---|---|---|
| **Momentum** | `log P_{t-21} − log P_{t-252}` (skip-1-month) | `market_data.csv` | ✅ HAVE |
| **LowVol** | `−σ(log_ret)` 252d, hoặc EWMA λ=0.94 | `market_data.csv` | ✅ HAVE |
| **Beta** | OLS vs VN-Index 252d, exp-decay weight half-life 63d (Barra USE4) | `market_data` + `vnindex_cache` | ✅ HAVE |
| **Size** | `log(close × shares_out)` | + `shares_outstanding` quarterly snapshot | ❌ FETCH |
| **Value** | z-score composite `B/P + E/P + S/P` | + BVPS / EPS_TTM / SPS_TTM quarterly | ❌ FETCH |
| **Quality** | `z(ROE) − 0.5·z(D/E) + 0.5·z(GrossMargin)` | + ROE / D/E / GM quarterly | ❌ FETCH |
| **Industry** | 10 ICB-L2 dummy | + ICB classification per mã | ❌ FETCH 1-time |

### 12.2. Cross-sectional regression spec
- **Monthly rebalance** WLS: weight = `√MCap` (Barra USE4 spec)
- **Shrinkage**: shrink covariance to identity 10% (small universe ~250 + size–beta collinearity cao ở VN)
- **Output**:
  - Factor return time series `[6 style + 10 industry]`
  - Per-stock exposure matrix `[N×16]` mỗi tháng
  - Idiosyncratic alpha residual `ε_i,t`
  - Factor t-stat (Fama-MacBeth standard error)

### 12.3. vnstock data constraints (free tier, confirmed 2026-05-18)

| Tier | Rate limit | BCTC history | Cost |
|---|---|---|---|
| **Guest** (no signup) | 20 req/min | **4 kỳ only** (1 năm quarterly) | Free + ads |
| **Community** (free signup) | 60 req/min | **8 kỳ** (2 năm quarterly) | Free |
| **Sponsor** | 60-100 req/min | Full (10+ năm) | Paid |

**Source priority**: VCI (60/min, cần key) > KBS (20/min, cần key) > MSN (no key, KHÔNG có VN equity, chỉ forex/crypto).

**Implication cho factor model**:
- ✅ Phase 1 (3 factor không cần BCTC) — free Guest tier OK.
- ⚠️ Phase 2 (Size/Value/Quality) — free Community = 8 quý = **2 năm history** → cross-sectional regression CHO HIỆN TẠI work fine; **backtest factor return 8 quý KHÔNG đủ power** cho Deflated SR + Fama-MacBeth t-stat valid.
- ❌ Backtest serious (5+ năm) → **bắt buộc Sponsor paid tier**.

### 12.4. Phase plan

| Phase | Thời gian | Data tier | Output |
|---|---|---|---|
| **P1 MVP** | 1 tuần | Free Guest | 3 factor (Mom/LowVol/Beta), cross-sectional regression infra, UI + AI CIO snapshot. Đủ validate workflow. |
| **P2 Full live** | +2-3 tuần | Free Community | + Size/Value/Quality + industry. Live signal OK; backtest weak (2 năm). |
| **P3 Backtest valid** | +1 tuần | Sponsor paid | 5+ năm fundamental → Deflated SR, factor t-stat, Fama-MacBeth SE valid. |

### 12.5. Critical caveats trước khi build

1. **Price adjustment**: verify `market_data.csv` là **adjusted close** (split + cash dividend) hay raw. Check `command/update_data.py:Quote.history()` flag. Raw close → ex-date return jump phá Momentum + Beta signal.
2. **Survivorship bias**: `tickers.csv` = **current** universe → factor backtest over-estimate (miss delisted HVN/FLC/ROS period). Cần point-in-time historical add/delist HSX cho backtest path.
3. **Free float adjust**: state-owned (BID, VCB, GAS, BSR, ACV) có total MCap gấp 3-5× free float. Phase 3 mới handle; Phase 1-2 dùng total shares + note caveat.
4. **Fundamental restatement** (VN habit: Q4 audit restate cả Q1-3): cần `as_of_date` field để point-in-time correct (avoid look-ahead trong backtest).
5. **Risk-free rate**: VGB 1Y yield cho excess return. Tạm fix 4.5% nếu lười fetch — error nhỏ vì cross-sectional regression chủ yếu dùng excess return.

### 12.6. File plan

```
tools/factor_risk_model/
  quant/
    factors.py        — compute_momentum / lowvol / beta / size / value / quality
    regression.py     — cross_sectional_wls(), shrinkage, fama_macbeth_se()
    metadata.py       — industry mapping helper
  ui/charts.py        — factor return time series + exposure heatmap + decile spread
  page.py             — render() + sidebar
  report.py           — snapshot dict cho AI CIO
command/
  update_fundamentals.py    — fetch BVPS/EPS/SPS/ROE/DE quarterly via vnstock.Finance, Community tier
  build_ticker_meta.py      — 1-time: shares_out + ICB-L2 per mã
data_lake/
  fundamentals_long.csv     — [ticker, quarter_end, bvps, eps_ttm, sps_ttm, roe, de, gm, as_of_date]
  ticker_meta.csv           — [ticker, icb_l1, icb_l2, free_float_pct]
  shares_outstanding.csv    — [ticker, date, shares_out]  (quarterly snapshot)
promt/
  factor_risk_promt.md      — v2 framework (PERSONA / Observations / Cross-Check / Verdict + JSON tail)
```

### 12.7. API budget (first backfill, ~250 mã)

| Endpoint | Calls/cycle | Note |
|---|---|---|
| `Listing().industries_icb()` (1-time) | 1 | ICB classification full |
| `Company(symbol).overview()` | 250 | shares_out + free_float |
| `Finance(symbol).balance_sheet(period='quarter')` | 250 × 1 (free) → 250 × 5 (sponsor) | 8 vs 20+ quarters |
| `Finance(symbol).income_statement(period='quarter')` | 250 | NI + revenue |
| `Finance(symbol).ratio(period='quarter')` | 250 | ROE, D/E |

**Throughput**: free Community 60 req/min → 1000 calls ≈ 17 phút. Sponsor 100 req/min → 10 phút. Cập nhật incremental sau quarter-end ~250 calls × 3 endpoint = 13 phút free tier.

---

## 13. Pairs Trading Research Lab — Build Spec (PROPOSED 2026-05-18)

**Posture**: Engle-Granger + Johansen + OU half-life filter cho mean-reversion pair trading trên cluster cointegrated VN. Tier A roadmap #8. Branch target: `B_Micro_Analysis` (đang trống). **KHÔNG plug vào AI CIO synthesis** — đứng độc lập như research dashboard.

### 13.1. Tại sao VN là môi trường lý tưởng

1. **Retail dominance ~75% volume** → emotion-driven decoupling lặp lại; mean-reversion edge tồn tại lâu vì ít smart money arb đi.
2. **Forced flow events có lịch trước**: VN30 ETF rebalance quarterly, foreign ownership limit (FOL) cap, margin call cascade → spread compression/expansion calendar-tradable.
3. **No real short ngoài VN30F1M futures** → ai cũng phải hedge qua basket → tạo basis spread.

### 13.2. Cluster cointegrated thực tế

| Cluster | Mã | Logic kinh tế | Test khuyến nghị |
|---|---|---|---|
| **Vingroup** | VIC, VHM, VRE | Same parent, FII flow shared | Johansen 3-way |
| **Big-4 SOE bank** | VCB, CTG, BID, MBB | Regulated rate, deposit base, NIM cycle | Johansen 4-way |
| **Steel** | HPG, HSG, NKG | Iron ore + rebar/galvanized cycle | Johansen 3-way |
| **Securities** | SSI, HCM, VND, VCI | Brokerage commission cycle | EG pair-wise |
| **Private bank** | VPB, STB, ACB, SHB | Retail loan book ⚠️ FOL risk | EG pair-wise (exclude FOL-near) |
| **Oil & Gas** | GAS, PLX, BSR, PVS | Brent + USD/VND link | Johansen 4-way |
| **Utility / Power** | REE, GEX, POW, HDG | Capacity factor, El Niño cycle | EG pair-wise |

VIC/VHM/VRE và VCB/CTG/BID là 2 candidate mạnh nhất (verified trong literature VN — UEH papers).

### 13.3. Spec kỹ thuật 4 stage

**Stage 1 — Cointegration test**
- Engle-Granger 2-step (pair): OLS `Y = α + β·X` → ADF residual, MacKinnon critical. Đủ cho 1300+ obs daily.
- Johansen (triplet/cluster): `statsmodels.tsa.vector_ar.vecm.coint_johansen`, λ_max + trace stat.

**Stage 2 — Spread dynamics filter**
- OU half-life: fit AR(1) `Δspread_t = θ(μ − spread_{t-1}) + ε_t`; `half_life = ln(2)/θ`.
- **Trade chỉ pair half-life 5-30 ngày** — <5 = noise (phí ăn hết); >30 = drift/regime change.
- Backup filter: Hurst H < 0.5 confirm anti-persistent.

**Stage 3 — Entry/exit rule**
- Z-score 60d rolling
- Entry: |z| > 2 (long low leg, short high leg)
- Exit: z crosses 0 hoặc time-stop 2× half-life
- Stop-loss: |z| > 3 → cointegration breakdown → exit + quarantine pair 60 ngày
- Re-test cointegration mỗi 60 phiên; pair fail → kill position

**Stage 4 — Position sizing**
- Hedge ratio β từ EG step 1 hoặc Johansen β vector
- Adjust lot size 100 → rounding error ~1-3% theoretical hedge
- 50/50 long-short market-neutral hoặc beta-weighted vs VN-Index

### 13.4. VN-specific gotchas (kill 70% paper backtest)

| # | Gotcha | Tác động | Mitigation |
|---|---|---|---|
| 1 | **Margin call T+2 cascade** | Spread widen 4-5σ trước revert → forced close ở đáy | Capital cushion ≥ 2× initial margin, intraday MtM check |
| 2 | **Foreign ownership limit (FOL)** | VPB/HDB/STB hit FOL → decoupling KHÔNG mean-revert | Exclude pair có 1 leg foreign room < 5% |
| 3 | **Corporate action** | Split/divvy không adjust → fake spread jump | Verify `Quote.history(adjusted=True)` flag |
| 4 | **Lot 100 + tick 50 VND** | Bid-ask eats ~10-20 bps/round-trip | Filter half-life ≥ 5 ngày |
| 5 | **No real short** | Chỉ short qua VN30F1M basket | Mã ngoài VN30 chỉ long-only ratio |
| 6 | **Lunch break gap 11:30-13:00** | Reopen ±2σ random walk | Time stop theo trading hour, không calendar |

### 13.5. Tại sao tách khỏi AI CIO synthesis

AI CIO pattern: 9 tool đo regime → 1 score 0-100 → 1 verdict allocation. Pairs signal:
- Per-pair, per-day, discrete event (long VIC/short VHM, z=-2.3, half-life 12d)
- KHÔNG aggregate được vào "regime"
- Time-sensitive (14:45 cron publish → entry có thể đã gone)
- Risk orthogonal với long-only equity allocation (market-neutral basket)

→ Inject pairs signal vào executive summary master prompt sẽ pollute regime narrative. **Pattern đúng**: standalone research dashboard với live table sorted by |z|, backtest panel riêng, KHÔNG plug `shared/ai_cio.py`.

### 13.6. File plan

```
tools/pairs_trading/
  quant/
    cointegration.py    — engle_granger(), johansen_test(), ou_half_life(), hurst()
    signal.py           — z_score_60d(), entry_exit_rules(), stop_loss()
    backtest.py         — basket_pnl(), transaction_cost_model(), margin_calc()
    clusters.py         — PREDEFINED_CLUSTERS dict (VINGROUP, BIG4_BANK, STEEL, ...)
  ui/
    charts.py           — spread plot, z-score gauge, equity curve
    sidebar.py          — cluster picker, |z| threshold tuner, half-life filter
  page.py
  # KHÔNG có report.py — không feed AI CIO
pages/tools_page_B/
  _N_Pairs_Trading.py   — entry, branch B_Micro_Analysis
```

**Dependency**: 0 mới. `market_data.csv` đã đủ 5+ năm. `statsmodels.tsa.vector_ar.vecm` đã có trong requirements.

### 13.7. Honest evaluation

| Dimension | Score | Reason |
|---|---|---|
| Signal-to-noise (VN) | 🟢 8/10 | Retail decoupling tạo edge bền |
| Data availability | 🟢 10/10 | 0 fetch mới, market_data đủ — không có blocker như §12 |
| Backtestability | 🟢 9/10 | 5+ năm history, survivorship VN30 thấp |
| Execution gap (paper→live) | 🔴 5/10 | T+2, FOL, lot size → 3-4% theoretical edge ăn mất qua phí |
| AI CIO synergy | 🔴 2/10 | Orthogonal, KHÔNG plug synthesis |
| Audience fit | 🟡 6/10 | Chỉ user trade chủ động |
| Effort | 🟡 1-2 tuần MVP | EG + Johansen + OU + dashboard. Live execution +1 tuần. |

### 13.8. Phase plan

| Phase | Thời gian | Output |
|---|---|---|
| **P1 Research-only** | 5-7 ngày | Live signal table + backtest panel, **không có live trade rule**. Demo + edge measurement. |
| **P2 Live execution** | +1 tuần | Order ticket layer + margin calc + foreign room check + corp-action handler. Chỉ build sau khi P1 demo positive edge sau cost. |

**Suggested order trong roadmap**: build SAU DCC-GARCH (Tier A #5) vì DCC dynamic correlation matrix dùng được chéo cho pairs filter — cointegration + dynamic corr combined mạnh hơn EG đơn.
