# Quant Platform — Project Context for Claude

**Type:** Streamlit-based quantitative analysis platform cho thị trường VN.
**Stack:** Python 3.10-3.11 (production), Streamlit, pandas, scipy, plotly, scikit-learn, arch (GARCH), hmmlearn, numba, polars, fpdf2, statsmodels, fredapi, yfinance, OpenAI SDK.
**Last major update:** 2026-05-19 (GFCM + Pairs Trading shipped — xem `docs/skill.md` để biết full session log).

## Architecture (3-tier)

```
data_lake/    — CSV cache (market_data, market_volume, vnindex/vn30, fundamentals,
                fed_liquidity, global_financial_conditions, ticker_metadata, Ai_cio_report)
shared/       — Cross-tool utilities (data_loader, ai_cio, daily_cache, dcc_garch,
                github_sync, api_key_helper, history_selector)
tools/<name>/ — Per-tool: quant/ (logic) + ui/ (charts, sidebar) + page.py (Streamlit render)
                + report.py (snapshot, optional — chỉ cần nếu plug AI CIO executive summary)
pages/        — Streamlit MPA entries:
                  A_Macro_Analysis    (Fed Liquidity, GFCM)
                  B_Micro_Analysis    (Pairs Trading)
                  C_Behavioral_Finance (9 VN-equity tools)
command/      — CLI scripts (update_data, update_fed_liquidity, update_global_financial_conditions,
                update_sector_data, run_ai_cio_auto, etc.)
promt/        — 12 AI prompt templates (typo intentional, hardcoded everywhere)
```

## 12 Tools Active

| # | Branch | Tool | Module | Key tech | AI |
|---|---|---|---|---|---|
| 1 | C | Fear & Greed | `fear_greed` | PCA + EGARCH→GARCH→EWMA fallback + Kelly skewness | exec-sum |
| 2 | C | Upside Ratio | `upside_ratio` | Hybrid Logit-AR + Beta-AR MC | exec-sum |
| 3 | C | Risk-Adjusted Growth | `risk_adjusted_growth` | Disciplined Return + Economic Alpha (banks) | exec-sum |
| 4 | C | Market Breadth | `market_breadth` | % stocks > MA20/60/125/252 | exec-sum |
| 5 | C | **ESR Monitor** | `esr_monitor` | 5-pillar SSI (S_VOL/S_PRES/S_COR/**S_LIQ=Volume Dry-Up**/S_VAL) + HMM | exec-sum |
| 6 | C | Dispersion | `dispersion` | CSAD/CSSD + DPI + Ledoit-Wolf | exec-sum |
| 7 | C | Manipulation | `manipulation` | PCA composite VIC/VHM/VRE vs VN30F1M, percentile regime | exec-sum |
| 8 | C | VaRES | `va_res` | Cornish-Fisher + Self-baseline Complacency | exec-sum |
| 9 | C | **Var-CVaR VNINDEX** | `var_cvar_vnindex` | Gaussian + Historical + **EVT POT-GPD** + Hill | exec-sum |
| 10 | A | Fed Liquidity | `fed_liquidity` | WALCL − TGA − RRP, Z-score 52W → ADD/CUT/HOLD | standalone |
| 11 | A | **GFCM** | `global_financial_conditions` | VIX + MOVE + HY/CCC OAS, static PCA, PC1_pct 1Y → STRESS/ELEVATED/CALM (FRED ICE BofA truncate ~3Y) | standalone |
| 12 | B | **Pairs Trading** | `pairs_trading` | EG + Johansen + OU half-life + Z-score 60d, 7 PREDEFINED clusters | none (orthogonal) |

**AI integration patterns**:
- **exec-sum**: tool có `report.py snapshot()`, được aggregate vào `shared/ai_cio.py:run_executive_summary()` cho 1 master verdict
- **standalone**: macro / cross-asset tool, AI analysis tab ngay trên page với prompt riêng — KHÔNG inject executive summary (giữ scope sạch)
- **none**: tool orthogonal (per-pair discrete signal) — KHÔNG plug AI CIO

## Critical Conventions

- **Universe**: `tickers.csv` (single source of truth, ~250 mã). KHÔNG hardcode list trong tool.
- **Quant layer**: KHÔNG import Streamlit. Errors RAISE — UI layer mới catch + log.
- **UI layer**: KHÔNG chứa business logic; chỉ render Plotly + Streamlit widgets.
- **AI prompts**: trong `promt/`, placeholders `{snake_case}` HOẶC `[Vietnamese Title]`. `ai_cio.py` `.replace()` literal — phải khớp 100%.
- **PRODUCTION_REGIME_METHOD** ở [tools/esr_monitor/quant/metrics.py:51](tools/esr_monitor/quant/metrics.py:51) = `'hmm'` cho live paths; backtest dùng `'hmm_walk_forward'` riêng.
- **Cache invalidation**: hash-based pkl cache key phải bao gồm `s_<feature>_method: "vN"` khi đổi methodology.
- **AI CIO history CSV** (`data_lake/Ai_cio_report.csv`) tự upsert khi `run_executive_summary()` chạy. Same-day → overwrite; T+1 → append.
- **Macro / cross-asset tool pattern**: theo precedent `fed_liquidity` / `global_financial_conditions` — AI tab riêng trên page với prompt template riêng, **không** inject `shared/ai_cio.py`. Executive summary scope = 9 VN-equity tools only.

## DON'Ts (Anti-patterns đã học)

- ❌ KHÔNG cho Margin khi Score > 80 vol thấp — bull top trap pattern
- ❌ KHÔNG đưa mức giá tuyệt đối VN stock trong AI report (training data cũ 2-3 năm). Manipulation prompt inject real-time `{vic_close}` `{vhm_close}` `{vre_close}` `{f1m_close}` từ `df_prices.iloc[-1]`
- ❌ KHÔNG dùng Amihud illiquidity cho VN30 bluechips — không correlate với stress. Đã thay bằng Volume Dry-Up
- ❌ KHÔNG `except Exception` rộng — quant phải raise; UI mới catch + log
- ❌ KHÔNG hardcode list `tool_names` trong `_clear_all_tool_caches` — thêm tool mới sẽ quên
- ❌ KHÔNG tạo `command/config.py` shim — Python module collision với root config
- ❌ KHÔNG inject macro / cross-asset tool vào executive summary aggregator — dilute scope; theo pattern fed_liquidity / GFCM

## Commands

```bash
# Local app
streamlit run app.py

# Data updates
python command/update_data.py                          # daily price+volume ~5 min
python command/update_data.py --backfill 2190          # 6 năm backfill
python command/update_bank_fundamentals.py             # quarterly
python command/update_fed_liquidity.py                 # weekly Wed (FRED WALCL/TGA/RRP)
python command/update_global_financial_conditions.py   # daily (FRED VIX/HY/CCC + Yahoo MOVE)
python command/update_sector_data.py                   # quarterly ICB metadata

# AI CIO
python command/run_ai_cio_auto.py --force              # manual refresh

# Smoke test
python3 -m py_compile <file>
```

## Active Permission Mode

`.claude/settings.local.json` đã set `defaultMode: "bypassPermissions"` + `skipDangerousModePermissionPrompt: true` + `skipAutoPermissionPrompt: true` ở **ROOT level** → Claude CLI KHÔNG hỏi xác nhận khi chạy Bash/Edit. Thiếu gate root-level thì silently fallback default mode.

Allowlist: `python3 *`, `python *`, `pip *`, `grep *`, `find *`, `ls *`, `cat *`, `git *`, `streamlit *`. Bypass mode cover hết.

## Recent Open Issues

1. **God module**: `shared/ai_cio.py` 700+ dòng — recommend refactor sang registry pattern (thêm tool mới phải edit list `tool_names` manual)
2. **Cache key dùng `date.today()`**: timezone bug Streamlit Cloud (UTC) vs VN (UTC+7) → đổi sang `df_stocks.index[-1]`
3. **`_create_pdf` duplicate**: trong `app.py:193` và `command/run_ai_cio_auto.py:79` → extract `shared/pdf_export.py`
4. **DCC-GARCH chưa wire vào Pairs Trading filter** (defer V2 — cointegration + dynamic corr combined)
5. **Pairs Aggregate Backtest** chưa stress-test cluster 6-way → có thể timeout Cloud (60s default) — cần `@st.cache_data` hoặc background job
6. **61 instances `except Exception` rộng** — mất stacktrace prod fail
7. ✅ ~~Hardcoded `t0_dt` manipulation~~ → FIXED 2026-05-18 (dynamic `result_df.index[-60]`)
8. ✅ ~~Module resolution Streamlit Cloud~~ → FIXED 2026-05-17 (`__init__.py` cho `command/`, `pages/`, `pages/tools_page_C/`)

## 🚧 Pending Build Backlog

| # | Tool | Trạng thái | Blocker / Next step |
|---|---|---|---|
| **§12** | **Factor Risk Model** (Barra-VN lite, 6 style + ~10 industry, cross-sectional WLS) | 🚧 PROPOSED 2026-05-18 — chưa code | vnstock free Community = 8 quý BCTC (~2 năm) → backtest 5+ năm cần Sponsor paid. **P1 (3-factor: Mom/LowVol/Beta — không cần BCTC) ship được ngay** với free tier |
| §3 | MES / SRISK (NYU V-Lab) | 📋 idea | — |
| §4 | Diebold-Yilmaz Spillover (VAR + FEVD) | 📋 idea | — |
| §6 | HRP thay logistic backtest curve | 📋 idea | — |
| §7 | Deflated Sharpe / PSR | 📋 idea | — |
| ✅ §13 | Pairs Trading Lab | **SHIPPED 2026-05-19** (PR #2 merged) | Live signals + 5 tabs + 7 clusters; DCC filter defer V2 |
| ✅ §14 | GFCM (Global Financial Conditions) | **SHIPPED 2026-05-19** (PR #6 merged) | VIX + MOVE + HY/CCC OAS, static PCA, regime via PC1_pct 1Y (ICE BofA truncate constraint) |

**Quy tắc khi resume**: đọc `docs/skill.md` (~300 dòng, compressed history) để pick up đầy đủ context trước khi code.

## When Working in This Project

- Đọc `docs/skill.md` để biết full session history nếu cần ngữ cảnh sâu
- Verify placeholder compat trước khi sửa prompts: grep `\[.*\]` trong prompt vs `.replace("...")` trong `ai_cio.py` / page.py
- Cache stale là vấn đề thường gặp sau khi đổi methodology → bump version flag trong cache key
- Numba kernels phải có parity test với pandas equivalent (xem `_rolling_es_kernel` pattern, diff < 1e-15)
- Khi build macro / cross-asset tool: theo precedent `fed_liquidity` / `global_financial_conditions` — standalone AI tab trên page, không touch `shared/ai_cio.py`
- Khi build VN-equity tool: theo precedent C-branch tools — `report.py snapshot()` + register vào `shared/ai_cio.py:run_<tool>()` + update `_clear_all_tool_caches` list
