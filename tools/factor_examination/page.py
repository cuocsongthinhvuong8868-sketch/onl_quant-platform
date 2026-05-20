"""
page.py — Factor Examination Streamlit page.

4 tabs:
  1. Universe Ranking      — heatmap top/bottom 20 + decile distribution + sector mix
  2. Portfolio Examination — upload/paste holdings → radar + per-stock rank + AI summary
  3. Single Ticker Profile — bar chart factor profile + closest peers (Euclidean)
  4. Forward IC Validation — Spearman IC time series + decile spread cumulative

Tool pattern: macro/standalone (precedent fed_liquidity, GFCM).
KHÔNG inject shared/ai_cio.py executive summary.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from openai import OpenAI

from config import AI_PROVIDER_MAP, AI_TEMPERATURE, DATA_LAKE, ROOT_DIR
from shared.data_loader import (
    load_close_prices,
    load_volumes,
    load_custom,
    load_ticker_metadata,
)
from tools.factor_examination.quant.factors import (
    compute_all_factors,
    FACTOR_NAMES,
)
from tools.factor_examination.quant.scoring import build_score_table
from tools.factor_examination.quant.portfolio import (
    parse_holdings_text,
    parse_holdings_csv,
    normalize_weights,
    aggregate_portfolio,
    find_peers,
)
from tools.factor_examination.quant.ic_validation import run_ic_backtest, HORIZONS
from tools.factor_examination.ui.sidebar import render_sidebar
from tools.factor_examination.ui.charts import (
    render_factor_heatmap,
    render_decile_distribution,
    render_sector_composition,
    render_factor_radar,
    render_holdings_table_chart,
    render_ticker_factor_bar,
    render_ic_timeseries,
    render_decile_cum,
)

logger = logging.getLogger(__name__)


# ── Universe filtering ──────────────────────────────────────
EXCLUDE_PATTERNS = ("FUEV", "FUET", "E1VFVN30", "VN30F")  # ETF + futures


def _build_universe(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    min_adv_billion: float,
) -> list[str]:
    """Filter universe: exclude ETF/futures, require min ADV20d."""
    cols = [c for c in prices.columns if not any(c.startswith(p) for p in EXCLUDE_PATTERNS)]
    if min_adv_billion <= 0:
        return cols
    # VN price quote = ngàn VND, volume = shares → product = ngàn VND.
    # Chia 1e6 để ra tỷ VND.
    if len(prices) < 20:
        return cols
    dollar_vol = (prices[cols] * volumes[cols]).iloc[-20:]
    median_dv_billion = dollar_vol.median() / 1e6
    keep = median_dv_billion[median_dv_billion >= min_adv_billion].index.tolist()
    return keep


# ── Cached pipeline ─────────────────────────────────────────
@st.cache_data(ttl=86400, show_spinner=False)
def _cached_score_table(
    prices_key: str,
    universe_hash: str,
    sector_neutral: bool,
    _prices: pd.DataFrame,
    _volumes: pd.DataFrame,
    _market: pd.Series,
    _metadata: pd.DataFrame | None,
    universe: tuple[str, ...],
) -> dict:
    """Cache key = (latest_date, universe_hash, sector_neutral, 'v1')."""
    universe_list = list(universe)
    prices_u = _prices[universe_list]
    volumes_u = _volumes[universe_list]
    factors = compute_all_factors(prices_u, volumes_u, _market)
    scored = build_score_table(factors, _metadata, sector_neutral=sector_neutral)
    return scored


@st.cache_data(ttl=86400, show_spinner=False)
def _cached_ic(
    prices_key: str,
    universe_hash: str,
    sector_neutral: bool,
    lookback_years: int,
    _prices: pd.DataFrame,
    _volumes: pd.DataFrame,
    _market: pd.Series,
    _metadata: pd.DataFrame | None,
    universe: tuple[str, ...],
) -> dict:
    universe_list = list(universe)
    return run_ic_backtest(
        _prices[universe_list], _volumes[universe_list], _market, _metadata,
        sector_neutral=sector_neutral, lookback_years=lookback_years,
    )


# ── Helpers ─────────────────────────────────────────────────
def _benchmark_exposure(z_table: pd.DataFrame) -> pd.Series:
    """Equal-weight benchmark = mean z (sau sector-neutral, mean ~0 nhưng có thể ±)."""
    return z_table.mean(axis=0)


def _format_table_for_display(holdings_table: pd.DataFrame) -> pd.DataFrame:
    df = holdings_table.copy()
    df["weight"] = df["weight"].apply(lambda x: f"{x:.1%}")
    df["composite_z"] = df["composite_z"].apply(lambda x: f"{x:+.2f}" if pd.notna(x) else "—")
    df["rank_pct"] = df["rank_pct"].apply(lambda x: f"p{x:.0f}" if pd.notna(x) else "—")
    df["top_z"] = df["top_z"].apply(lambda x: f"{x:+.2f}" if pd.notna(x) else "—")
    df["weak_z"] = df["weak_z"].apply(lambda x: f"{x:+.2f}" if pd.notna(x) else "—")
    return df


def _portfolio_pct_estimate(port_composite: float, composite_universe: pd.Series) -> float:
    """Estimate percentile rank của portfolio composite trong universe distribution."""
    valid = composite_universe.dropna()
    if valid.empty:
        return np.nan
    return float((valid < port_composite).mean() * 100.0)


# ── Tabs ────────────────────────────────────────────────────
def _tab_universe(scored: dict, sector_map: pd.Series) -> None:
    composite = scored["composite"]
    z_table = scored["z"]
    valid = composite.dropna().sort_values(ascending=False)

    if len(valid) < 30:
        st.error(f"Universe chỉ có {len(valid)} mã valid — không đủ cho ranking. Tăng backfill data hoặc giảm Min ADV.")
        return

    st.markdown(f"**Universe size**: {len(valid)} mã (sau filter).")

    strong = valid[valid >= 1.0]
    weak = valid[valid <= -1.0]
    neutral = valid[(valid > -0.5) & (valid < 0.5)]

    col_a, col_b, col_c = st.columns(3)
    col_a.metric(
        "🟢 Strong (≥ +1σ)",
        f"{len(strong)} mã",
        help=(
            f"Top: {strong.index[0]} ({strong.iloc[0]:+.2f}σ)"
            if not strong.empty else "Không có mã ≥ +1σ"
        ),
    )
    col_b.metric(
        "⚪ Neutral (|z| < 0.5σ)",
        f"{len(neutral)} mã",
        help=f"{len(neutral) / len(valid) * 100:.0f}% universe",
    )
    col_c.metric(
        "🔴 Weak (≤ -1σ)",
        f"{len(weak)} mã",
        help=(
            f"Bottom: {weak.index[-1]} ({weak.iloc[-1]:+.2f}σ)"
            if not weak.empty else "Không có mã ≤ -1σ"
        ),
    )

    st.markdown("---")
    col_top, col_bot = st.columns(2)
    top_20 = valid.head(20).index.tolist()
    bot_20 = valid.tail(20).index.tolist()
    with col_top:
        st.plotly_chart(
            render_factor_heatmap(z_table, top_20, "🟢 Top 20 composite"),
            use_container_width=True,
        )
    with col_bot:
        st.plotly_chart(
            render_factor_heatmap(z_table, bot_20[::-1], "🔴 Bottom 20 composite"),
            use_container_width=True,
        )

    st.markdown("---")
    col_d, col_e = st.columns(2)
    with col_d:
        st.plotly_chart(render_decile_distribution(composite), use_container_width=True)
    with col_e:
        decile_top_n = max(10, int(len(valid) * 0.1))
        st.plotly_chart(
            render_sector_composition(
                valid.head(decile_top_n).index.tolist(),
                valid.tail(decile_top_n).index.tolist(),
                sector_map,
            ),
            use_container_width=True,
        )


def _tab_portfolio(scored: dict, params: dict) -> None:
    composite = scored["composite"]
    rank_pct = scored["rank_pct"]
    z_table = scored["z"]
    sector_map = scored["sector_map"]

    st.markdown("### Nhập portfolio")
    input_mode = st.radio(
        "Cách nhập",
        ["📋 Paste text", "📁 Upload CSV"],
        horizontal=True,
        key="fexam_input_mode",
    )

    holdings = {}
    if input_mode == "📋 Paste text":
        text = st.text_area(
            "Format: `ticker, weight` mỗi dòng (weight có thể là fraction 0.15 hoặc % 15%)",
            value="",
            height=200,
            placeholder="VIC, 0.15\nVHM, 0.10\nFPT, 12%\n...",
            key="fexam_text",
        )
        if text:
            try:
                holdings = parse_holdings_text(text)
            except Exception as exc:
                st.error(f"Lỗi parse text: {exc}")
                return
    else:
        uploaded = st.file_uploader("CSV file (cột ticker + weight)", type=["csv"], key="fexam_csv")
        if uploaded is not None:
            try:
                holdings = parse_holdings_csv(uploaded.read())
            except Exception as exc:
                st.error(f"Lỗi parse CSV: {exc}")
                return

    if not holdings:
        st.info("👆 Nhập portfolio để bắt đầu phân tích.")
        return

    try:
        holdings_norm = normalize_weights(holdings)
    except Exception as exc:
        st.error(str(exc))
        return

    try:
        agg = aggregate_portfolio(holdings_norm, z_table, composite, rank_pct, sector_map)
    except Exception as exc:
        st.error(f"Aggregate fail: {exc}")
        return

    port_pct = _portfolio_pct_estimate(agg["portfolio_composite"], composite)

    # ── Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Holdings (in universe)", len(agg["holdings_table"]))
    col2.metric("Portfolio composite z", f"{agg['portfolio_composite']:+.2f}σ")
    col3.metric(
        "Estimated rank pct",
        f"{port_pct:.0f}%" if pd.notna(port_pct) else "—",
        help="Vị trí composite portfolio trong distribution của universe",
    )
    col4.metric("Concentration alerts", len(agg["concentration"]),
                help="Factor có |exposure| > 1σ")

    if agg["missing"]:
        st.warning(
            f"⚠️ Holdings ngoài universe (bỏ qua): {', '.join(agg['missing'])}",
            icon="⚠️",
        )

    # ── Factor radar
    st.markdown("---")
    bench = _benchmark_exposure(z_table)
    st.plotly_chart(
        render_factor_radar(agg["factor_exposure"], bench),
        use_container_width=True,
    )

    # ── Concentration alerts
    if not agg["concentration"].empty:
        st.markdown("#### 🚨 Concentration Alerts (|exposure| > 1σ)")
        conc_rows = []
        for factor, exp in agg["concentration"].items():
            conc_rows.append({
                "Factor": factor,
                "Exposure": f"{exp:+.2f}σ",
                "Direction": "📈 Tilt mạnh vào factor" if exp > 0 else "📉 Tilt ngược factor",
            })
        st.dataframe(pd.DataFrame(conc_rows), use_container_width=True, hide_index=True)

    # ── Sector breakdown
    st.markdown("#### Sector concentration")
    sec_df = agg["sector_weights"].rename("weight").reset_index()
    sec_df.columns = ["Sector", "Weight"]
    sec_df["Weight"] = sec_df["Weight"].apply(lambda x: f"{x:.1%}")
    st.dataframe(sec_df, use_container_width=True, hide_index=True)

    # ── Holdings table
    st.markdown("#### Holdings detail (ranked by composite)")
    st.plotly_chart(render_holdings_table_chart(agg["holdings_table"]), use_container_width=True)
    st.dataframe(
        _format_table_for_display(agg["holdings_table"]),
        use_container_width=True, hide_index=True,
    )

    # ── AI section
    st.markdown("---")
    _render_ai_section(scored, agg, port_pct, params)


def _tab_ticker_profile(scored: dict, prices: pd.DataFrame) -> None:
    composite = scored["composite"]
    z_table = scored["z"]
    sector_map = scored["sector_map"]
    rank_pct = scored["rank_pct"]
    raw_factors = scored["raw"]

    universe_list = composite.dropna().index.tolist()
    if not universe_list:
        st.error("Không có ticker nào valid trong universe")
        return

    selected = st.selectbox(
        "Chọn ticker để xem profile",
        options=universe_list,
        key="fexam_ticker_select",
    )

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Composite z", f"{composite.loc[selected]:+.2f}σ")
    col_b.metric("Rank pct (universe)", f"p{rank_pct.loc[selected]:.0f}")
    col_c.metric("Sector", sector_map.loc[selected] if selected in sector_map.index else "—")
    last_close = prices[selected].dropna().iloc[-1] if selected in prices.columns else np.nan
    col_d.metric("Last close", f"{last_close:,.0f}" if pd.notna(last_close) else "—")

    st.markdown("---")
    st.plotly_chart(
        render_ticker_factor_bar(z_table.loc[selected], selected),
        use_container_width=True,
    )

    # Raw values
    with st.expander("📊 Raw factor values (chưa z-score)"):
        raw_row = raw_factors.loc[selected]
        df_raw = raw_row.rename("value").reset_index()
        df_raw.columns = ["Factor", "Raw value"]
        df_raw["Raw value"] = df_raw["Raw value"].apply(
            lambda x: f"{x:.4f}" if pd.notna(x) else "—"
        )
        st.dataframe(df_raw, use_container_width=True, hide_index=True)

    # Closest peers
    st.markdown("#### Closest peers (Euclidean distance trong factor space)")
    try:
        peers = find_peers(selected, z_table, sector_map, n=10)
        peers["distance"] = peers["distance"].round(2)
        st.dataframe(peers, use_container_width=True, hide_index=True)
    except Exception as exc:
        st.warning(f"Peer lookup fail: {exc}")


def _tab_ic_validation(
    prices: pd.DataFrame, volumes: pd.DataFrame, market: pd.Series,
    metadata, params: dict, universe: list[str],
) -> None:
    st.markdown(
        f"### Forward IC Validation — lookback {params['ic_lookback']}Y"
    )
    st.caption(
        "Spearman rank IC giữa composite_t và forward return tại 3 horizon "
        "(21d / 63d / 126d = 1M/3M/6M). Snapshot mỗi 21 phiên. "
        "Decile spread: top 10% composite vs bottom 10% composite cumulative."
    )

    if st.button("🔬 Run IC backtest", type="primary", key="fexam_run_ic"):
        with st.spinner(f"Running IC backtest {params['ic_lookback']}Y..."):
            try:
                prices_key = str(prices.index[-1].date())
                universe_hash = str(hash(tuple(sorted(universe))))
                ic_result = _cached_ic(
                    prices_key, universe_hash,
                    params["sector_neutral"], params["ic_lookback"],
                    prices, volumes, market, metadata,
                    tuple(universe),
                )
                st.session_state["fexam_ic_result"] = ic_result
            except Exception as exc:
                st.error(f"IC backtest fail: {exc}")
                logger.exception("IC backtest fail")
                return

    if "fexam_ic_result" not in st.session_state:
        st.info("👆 Click 'Run IC backtest' để bắt đầu (~30-60s compute, cache 24h).")
        return

    result = st.session_state["fexam_ic_result"]
    summary = result["ic_summary"]
    ic_series = result["ic_series"]
    decile_cum = result["decile_cum"]

    st.markdown("#### Summary statistics")
    summary_disp = summary.copy()
    summary_disp["mean_ic"] = summary_disp["mean_ic"].apply(lambda x: f"{x:+.4f}")
    summary_disp["std_ic"] = summary_disp["std_ic"].apply(lambda x: f"{x:.4f}")
    summary_disp["ICIR"] = summary_disp["ICIR"].apply(
        lambda x: f"{x:+.2f}" if pd.notna(x) else "—"
    )
    summary_disp["hit_rate"] = summary_disp["hit_rate"].apply(lambda x: f"{x:.1%}")
    st.dataframe(summary_disp, use_container_width=True, hide_index=True)

    st.caption(
        "📌 **Đọc**: IC > 0 = composite có positive predictive power. "
        "ICIR > 0.5 = signal stable. Hit rate > 55% = consistent across snapshot."
    )

    st.markdown("#### IC time series")
    st.plotly_chart(render_ic_timeseries(ic_series), use_container_width=True)

    if not decile_cum.empty:
        st.markdown("#### Decile spread cumulative (21d forward holding)")
        st.plotly_chart(render_decile_cum(decile_cum), use_container_width=True)


# ── AI Section ──────────────────────────────────────────────
def _build_ai_prompt(scored: dict, agg: dict, port_pct: float, params: dict) -> tuple[str, str]:
    """Render system + user prompt từ template + data."""
    prompt_path = ROOT_DIR / "promt" / "factor_examination_promt.md"
    with open(prompt_path, "r", encoding="utf-8") as f:
        tmpl = f.read()

    today = datetime.now().strftime("%Y-%m-%d")
    exp = agg["factor_exposure"]
    holdings_tbl = agg["holdings_table"]
    top5 = holdings_tbl.head(5)
    bot5 = holdings_tbl.tail(5)

    def _table_md(df, columns):
        lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
        for _, row in df.iterrows():
            cells = []
            for c in columns:
                v = row.get(c, "—")
                if isinstance(v, float):
                    cells.append(f"{v:+.2f}" if abs(v) < 100 else f"{v:.0f}")
                else:
                    cells.append(str(v))
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines)

    top5_md = _table_md(top5, ["ticker", "weight", "composite_z", "rank_pct", "sector", "top_factor"])
    bot5_md = _table_md(bot5, ["ticker", "weight", "composite_z", "rank_pct", "sector", "weak_factor"])
    sec_breakdown = "\n".join(f"- {s}: {w:.1%}" for s, w in agg["sector_weights"].items())

    if agg["concentration"].empty:
        conc_md = "Không có factor nào vượt ±1σ — portfolio cân bằng."
    else:
        conc_md = "\n".join(f"- {f}: {v:+.2f}σ" for f, v in agg["concentration"].items())

    full_prompt = (
        tmpl
        .replace("[Nhập ngày]", today)
        .replace("[Universe_n]", str(len(scored["composite"].dropna())))
        .replace("[Min_ADV]", f"{params['min_adv_billion']:.1f}")
        .replace("[Sector_neutral_flag]", "True" if params["sector_neutral"] else "False")
        .replace("[N_holdings]", str(len(holdings_tbl)))
        .replace("[N_missing]", str(len(agg["missing"])))
        .replace("[Missing_list]", ", ".join(agg["missing"]) if agg["missing"] else "—")
        .replace("[Port_composite]", f"{agg['portfolio_composite']:+.2f}")
        .replace("[Port_pct]", f"{port_pct:.0f}" if pd.notna(port_pct) else "—")
        .replace("[Mom12_exp]", f"{exp.get('Mom_12_1', np.nan):+.2f}")
        .replace("[Mom6_exp]", f"{exp.get('Mom_6_1', np.nan):+.2f}")
        .replace("[STR_exp]", f"{exp.get('ST_Reversal', np.nan):+.2f}")
        .replace("[LTR_exp]", f"{exp.get('LT_Reversal', np.nan):+.2f}")
        .replace("[LV_exp]", f"{exp.get('LowVol', np.nan):+.2f}")
        .replace("[BL_exp]", f"{exp.get('Beta_Low', np.nan):+.2f}")
        .replace("[IV_exp]", f"{exp.get('IdioVol_Low', np.nan):+.2f}")
        .replace("[LIQ_exp]", f"{exp.get('Liquidity', np.nan):+.2f}")
        .replace("[SZ_exp]", f"{exp.get('Size', np.nan):+.2f}")
        .replace("[AL_exp]", f"{exp.get('Anti_Lottery', np.nan):+.2f}")
        .replace("[Sector_breakdown]", sec_breakdown)
        .replace("[Top5_table]", top5_md)
        .replace("[Bot5_table]", bot5_md)
        .replace("[Concentration_list]", conc_md)
    )

    parts = full_prompt.split("# INPUT")
    system_prompt = parts[0].strip()
    user_prompt = "# INPUT" + parts[1].strip() if len(parts) > 1 else full_prompt
    return system_prompt, user_prompt


def _render_ai_section(scored: dict, agg: dict, port_pct: float, params: dict) -> None:
    st.markdown("### 🤖 AI Analysis (Portfolio Examination)")

    api_key = params.get("api_key", "")
    ai_provider = params["ai_provider"]
    cfg = AI_PROVIDER_MAP[ai_provider]

    today_str = datetime.now().strftime("%d%m%y")
    ai_cache_file = (
        DATA_LAKE / "daily_cache"
        / f"factor_examination_{ai_provider}_{today_str}.txt"
    )

    tab_current, tab_history = st.tabs(["🚀 Phân tích hiện tại", "📅 Xem lại phân tích cũ"])

    with tab_current:
        if ai_cache_file.exists():
            st.success("Tải kết quả AI từ bộ nhớ tạm (Cache ngày)!")
            with open(ai_cache_file, "r", encoding="utf-8") as f:
                cached_result = f.read()
            with st.container(border=True):
                st.markdown(cached_result)

            from shared.github_sync import render_sync_button
            render_sync_button(ai_cache_file, key_suffix="fexam")

            st.info(
                "ℹ️ **Lưu ý**: Cache file lưu phân tích **mới nhất** của ngày + provider này. "
                "Nếu chạy portfolio khác (cùng ngày, cùng provider) sẽ overwrite — "
                "đẩy lên GitHub trước khi rerun nếu muốn giữ lịch sử portfolio cũ.",
                icon="ℹ️",
            )

            if st.button("🔄 Chạy lại phân tích AI (overwrite cache)",
                         type="secondary", key="fexam_rerun_ai"):
                os.remove(ai_cache_file)
                st.rerun()
        else:
            if not api_key:
                st.info("ℹ️ Nhập API Key ở sidebar để chạy AI analysis.")
                return

            btn_label = f"🐺 Phân tích Portfolio ({cfg['display']})"
            if not st.button(btn_label, type="primary", key="fexam_run_ai"):
                return

            with st.spinner("AI đang phân tích portfolio..."):
                try:
                    system_prompt, user_prompt = _build_ai_prompt(scored, agg, port_pct, params)
                    client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"])
                    response = client.chat.completions.create(
                        model=cfg["api_model"],
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=cfg.get("temperature", AI_TEMPERATURE),
                    )
                    result_text = response.choices[0].message.content

                    ai_cache_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(ai_cache_file, "w", encoding="utf-8") as f:
                        f.write(result_text)

                    st.success("Hoàn thành phân tích! Refresh tab để hiện nút Sync GitHub.")
                    with st.container(border=True):
                        st.markdown(result_text)
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi kết nối API: {e}")

    with tab_history:
        from shared.history_selector import build_history_options
        _all_caches = list(DATA_LAKE.glob("daily_cache/factor_examination_*.txt"))
        _options = build_history_options(
            _all_caches, "factor_examination", AI_PROVIDER_MAP
        )
        if not _options:
            st.info("ℹ️ Chưa có dữ liệu phân tích lịch sử.")
        else:
            _selected_label = st.selectbox(
                "📅 Chọn ngày và model:",
                options=list(_options.keys()),
                index=0,
                key="fexam_history_selector",
            )
            _sel_path = _options[_selected_label]
            with st.container(border=True):
                try:
                    with open(_sel_path, "r", encoding="utf-8") as f:
                        st.markdown(f.read())
                except Exception as e:
                    st.error(f"Lỗi đọc file: {e}")


# ── Main render ─────────────────────────────────────────────
def render() -> None:
    st.title("📐 Portfolio Factor Examination")
    st.caption(
        "Multi-factor cross-sectional stock scorer (10 factor price-based, sector-neutral ICB). "
        "Tool **portfolio examination** — KHÔNG phải regime classifier. "
        "Có alpha **chỉ khi human đánh giá regime từ tool khác** (GFCM/ESR) trước."
    )

    # ── Handbook download ──
    _hb = Path(__file__).resolve().parents[2] / "docs" / "factor_examination_handbook.md"
    if _hb.exists():
        _c1, _c2 = st.columns([3, 1])
        with _c1:
            st.caption(
                "📖 **Handbook** — hướng dẫn 10 factor, pipeline, đọc 4 tab, workflow "
                "human-in-the-loop, concentration alert reading, FAQ."
            )
        with _c2:
            st.download_button(
                label="⬇️ Tải Handbook (.md)",
                data=_hb.read_bytes(),
                file_name="factor_examination_handbook.md",
                mime="text/markdown",
                use_container_width=True,
                key="fexam_handbook_dl",
            )

    # Load data
    try:
        prices = load_close_prices()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    volumes = load_volumes()
    if volumes is None:
        st.error("market_volume.csv chưa tồn tại. Chạy `python command/update_data.py --backfill 2190`.")
        st.stop()

    try:
        vnindex = load_custom("vnindex_cache.csv")["VNINDEX"]
    except Exception as e:
        st.error(f"Lỗi load VN-Index: {e}")
        st.stop()

    metadata = load_ticker_metadata()
    if metadata is None:
        st.warning("⚠️ ticker_metadata.csv chưa có — sector-neutral sẽ về 'Other' cho mọi mã. "
                   "Chạy `python command/update_sector_data.py` để có ICB.")

    # Align market to prices index
    market = vnindex.reindex(prices.index).ffill()

    params = render_sidebar()

    # Build universe
    universe = _build_universe(prices, volumes, params["min_adv_billion"])
    if len(universe) < 30:
        st.error(
            f"Universe sau filter chỉ có {len(universe)} mã (<30 minimum). "
            f"Giảm Min ADV xuống (hiện {params['min_adv_billion']:.1f} tỷ)."
        )
        return

    prices_key = str(prices.index[-1].date())
    universe_hash = str(hash(tuple(sorted(universe))))

    with st.spinner(f"Computing factor exposures cho {len(universe)} mã..."):
        try:
            scored = _cached_score_table(
                prices_key, universe_hash, params["sector_neutral"],
                prices, volumes, market, metadata, tuple(universe),
            )
        except Exception as exc:
            st.error(f"Factor compute fail: {exc}")
            logger.exception("Factor compute fail")
            return

    tab1, tab2, tab3, tab4 = st.tabs([
        "🏆 Universe Ranking",
        "💼 Portfolio Examination",
        "🔍 Ticker Profile",
        "📊 Forward IC Validation",
    ])
    with tab1:
        _tab_universe(scored, scored["sector_map"])
    with tab2:
        _tab_portfolio(scored, params)
    with tab3:
        _tab_ticker_profile(scored, prices)
    with tab4:
        _tab_ic_validation(prices, volumes, market, metadata, params, universe)
