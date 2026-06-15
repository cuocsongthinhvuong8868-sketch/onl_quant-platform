"""
sidebar.py — Sidebar controls for Factor Examination tool.
"""
from __future__ import annotations

import streamlit as st


def render_sidebar() -> dict:
    """Render sidebar widgets. Trả dict params cho page.py."""
    st.sidebar.header("⚙️ Factor Examination")

    sector_neutral = st.sidebar.checkbox(
        "Sector-neutralize (ICB)",
        value=True,
        help="Trừ mean sector trước khi composite — fair across sector. "
             "Sector <5 mã gộp 'Other'.",
        key="fexam_sector_neutral",
    )

    min_adv_billion = st.sidebar.number_input(
        "Min ADV20d (tỷ VND)",
        min_value=0.0, max_value=200.0, value=1.0, step=0.5,
        help="Filter universe: bỏ mã có median dollar volume 20 ngày dưới ngưỡng. "
             "1 tỷ VND ≈ 50k USD/day liquidity.",
        key="fexam_min_adv",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Forward IC Validation**")
    ic_lookback = st.sidebar.slider(
        "Lookback IC backtest (năm)",
        min_value=1, max_value=5, value=3, step=1,
        key="fexam_ic_lookback",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("**AI Analysis**")
    from config import AI_PROVIDER_MAP
    ai_provider = st.sidebar.selectbox(
        "AI Provider",
        options=list(AI_PROVIDER_MAP.keys()),
        format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
        key="fexam_ai_provider",
    )
    api_key_raw = st.sidebar.text_input(
        "API Key (hoặc 4-digit shortcut)",
        type="password",
        key="fexam_api_key",
        help="Shortcut 4 số → resolve từ Streamlit Secrets `AI_KEY_xxxx`.",
    )
    from shared.api_key_helper import resolve_api_key
    api_key, api_key_msg, api_key_err = resolve_api_key(api_key_raw, ai_provider)
    if api_key_err:
        st.sidebar.error(api_key_msg)
    elif api_key_msg:
        st.sidebar.success(api_key_msg)

    return {
        "sector_neutral": sector_neutral,
        "min_adv_billion": min_adv_billion,
        "ic_lookback": ic_lookback,
        "ai_provider": ai_provider,
        "api_key": api_key,
    }
