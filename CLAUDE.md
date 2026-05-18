# Quant Platform — Project Context for Claude

**Type:** Streamlit-based quantitative analysis platform cho thị trường VN.
**Stack:** Python 3.10-3.11 (production), Streamlit, pandas, scipy, plotly, scikit-learn, arch (GARCH), hmmlearn, numba, polars, fpdf2, OpenAI SDK.
**Last major update:** 2026-05-17 (xem `docs/skill.md` để biết full session log).

## Architecture (3-tier)

```
data_lake/    — CSV cache (market_data, market_volume, vnindex/vn30, fundamentals, fed_liquidity)
shared/       — Cross-tool utilities (data_loader, ai_cio, daily_cache, github_sync, api_key_helper)
tools/<name>/ — Per-tool: quant/ (logic) + ui/ (charts) + page.py (Streamlit render) + report.py (snapshot)
pages/        — Streamlit MPA entries (3 nhánh: A_Macro / B_Micro / C_Behavioral)
command/      — CLI scripts (update_data, run_ai_cio_auto, etc.)
promt/        — AI prompt templates (typo intentional, hardcoded everywhere)
```

## 10 Tools Active

| # | Tool | Module | Key tech |
|---|---|---|---|
| 1 | Fear & Greed | `fear_greed` | PCA + EGARCH→GARCH→EWMA fallback chain + Kelly skewness |
| 2 | Upside Ratio | `upside_ratio` | Hybrid Logit-AR + Beta-AR Monte Carlo |
| 3 | Risk-Adjusted Growth | `risk_adjusted_growth` | Disciplined Return + Economic Alpha (banks) |
| 4 | Market Breadth | `market_breadth` | % stocks > MA20/60/125/252 |
| 5 | **ESR Monitor** | `esr_monitor` | 5-pillar SSI (S_VOL/S_PRES/S_COR/**S_LIQ=Volume Dry-Up**/S_VAL) + HMM regime |
| 6 | Dispersion | `dispersion` | CSAD/CSSD + DPI + Ledoit-Wolf |
| 7 | Manipulation | `manipulation` | PCA composite VIC/VHM/VRE vs VN30F1M, percentile regime |
| 8 | VaRES | `va_res` | Cornish-Fisher + Self-baseline Complacency |
| 9 | **Var-CVaR VNINDEX** | `var_cvar_vnindex` | Gaussian + Historical + **EVT POT-GPD** (99/99.5%) + Hill |
| 10 | Fed Liquidity (Macro) | `fed_liquidity` | WALCL − TGA − RRP, Z-score 52W → ADD/CUT/HOLD |

## Critical Conventions

- **Universe**: `tickers.csv` (single source of truth, ~250 mã). KHÔNG hardcode list trong từng tool.
- **Quant layer**: KHÔNG import Streamlit; UI layer KHÔNG chứa business logic.
- **AI prompts**: Trong `promt/`, placeholders dạng `{snake_case}` HOẶC `[Vietnamese Title]`. `ai_cio.py` `.replace()` literal — phải khớp 100%.
- **PRODUCTION_REGIME_METHOD** ở [tools/esr_monitor/quant/metrics.py:51](tools/esr_monitor/quant/metrics.py:51) = `'hmm'` — single source of truth cho live paths; backtest dùng `'hmm_walk_forward'` riêng.
- **Cache invalidation**: hash-based pkl cache key phải bao gồm `s_<feature>_method: "vN"` khi đổi methodology.
- **AI CIO history CSV** (`data_lake/Ai_cio_report.csv`) tự update khi `run_executive_summary()` chạy (cả manual app + cron auto). Same-day → overwrite; new day → append.

## DON'Ts (Anti-patterns đã học)

- ❌ KHÔNG cho phép Margin khi Score > 80 nếu vol thấp — đó là bull top trap pattern
- ❌ KHÔNG đưa mức giá tuyệt đối trong AI report (VD: "VIC mất 45,000" trong khi VIC = 228k). Training data cũ 2-3 năm. Prompts đã có rule cấm + manipulation prompt giờ inject real-time prices `{vic_close}` `{vhm_close}` `{vre_close}` `{f1m_close}`.
- ❌ KHÔNG dùng Amihud illiquidity cho VN30 bluechips — không correlate với stress. Đã thay bằng Volume Dry-Up (log ratio MA20/MA252 dollar volume).
- ❌ KHÔNG `except Exception` rộng (silently swallow errors). Quant layer phải raise; UI layer mới catch + log.
- ❌ KHÔNG hardcode list `tool_names` trong `_clear_all_tool_caches` — thêm tool mới sẽ quên update.
- ❌ KHÔNG tạo `command/config.py` shim — Python module collision với root config.

## Commands

```bash
# Local app
streamlit run app.py

# Data update (incremental, ~5 min cho 250 mã)
python command/update_data.py

# Backfill 6 năm (khi đổi schema)
python command/update_data.py --backfill 2190

# AI CIO force refresh
python command/run_ai_cio_auto.py --force

# Smoke test (cần stub numba/polars trên Python 3.14)
python3 -m py_compile <file>
```

## Active Permission Mode

`.claude/settings.local.json` đã set `defaultMode: "bypassPermissions"` + `skipDangerousModePermissionPrompt: true` → Claude CLI sẽ KHÔNG hỏi xác nhận khi chạy Bash/Edit trong directory này.

Allow list bao gồm: `python3/python/pip/grep/find/ls/cat/git/streamlit *`. Bypass cover hết.

## Recent Open Issues (cần fix sau)

1. **God module**: `shared/ai_cio.py` 600+ dòng — recommend refactor sang registry pattern
2. **Cache key dùng `date.today()`**: timezone bug giữa Streamlit Cloud (UTC) và VN (UTC+7). Đổi sang `df_stocks.index[-1]`.
3. ✅ ~~**Hardcoded `t0_dt = pd.to_datetime("2026-03-02")`** trong manipulation: làm dynamic 60 phiên gần nhất.~~ → FIXED 2026-05-18 (`shared/ai_cio.py:264` dùng `result_df.index[-60]`, mirror UI default).
4. **`_create_pdf` duplicate**: trong `app.py:193` và `command/run_ai_cio_auto.py:79` → extract `shared/pdf_export.py`.
5. **Streamlit Cloud module resolution**: đã thêm `__init__.py` cho `command/`, `pages/`, `pages/tools_page_C/` (2026-05-17 fix).

## 🚧 Pending Build Backlog (chưa hoàn thành, đề xuất tools mới)

| # | Tool | Trạng thái | Blocker / Next step |
|---|---|---|---|
| **§12** | **Factor Risk Model** (Barra-VN lite, 6 style + ~10 industry, cross-sectional WLS) | 🚧 PROPOSED 2026-05-18 — chưa code | vnstock free tier giới hạn BCTC 8 quý (~2 năm) → backtest 5+ năm cần Sponsor paid. Phase 1 (3 factor không cần BCTC) ship được ngay với free tier. |
| **§13** | **Pairs Trading research lab** (Engle-Granger + Johansen + OU half-life, KHÔNG plug AI CIO) | 🚧 PROPOSED 2026-05-18 — chưa code | 0 data blocker. Execution gap T+2/FOL/lot-size lớn → P1 research-only 5-7 ngày trước khi build live execution layer. |

**Quy tắc khi resume**: đọc `docs/skill.md` §12 (Factor Risk Model spec) và §13 (Pairs Trading spec) để pick up đầy đủ context trước khi code.

## When Working in This Project

- Đọc `docs/skill.md` để biết full session history nếu cần ngữ cảnh sâu hơn
- Verify placeholder compat trước khi sửa prompts: `python3 -c "..."` script ở §8 của skill.md
- Cache stale là vấn đề thường gặp sau khi đổi methodology → bump version flag trong cache key
- Numba kernels phải có parity test với pandas equivalent (xem `_rolling_es_kernel` pattern)
