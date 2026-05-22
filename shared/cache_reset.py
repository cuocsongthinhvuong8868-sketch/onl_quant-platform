"""
shared/cache_reset.py — Helper xoá compute cache cho toàn bộ tool.

Xoá:
  - `st.cache_data` toàn cục (mọi @st.cache_data của mọi tool)
  - File `.pkl` trong `data_lake/daily_cache/` (compute pickle của VN-equity tool
    qua shared/daily_cache.py)

KHÔNG xoá:
  - File `.txt` AI cache (AI output đắt $, người dùng có thể muốn giữ)
  - File CSV trong `data_lake/` (raw data, được update bởi cron)
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from config import DATA_LAKE


def reset_all_compute_caches() -> dict:
    """Clear toàn bộ compute cache (Streamlit + on-disk pkl).

    Returns
    -------
    dict
        {"pkl_deleted": int, "streamlit_cleared": bool}
    """
    st.cache_data.clear()

    pkl_dir = DATA_LAKE / "daily_cache"
    deleted = 0
    if pkl_dir.exists():
        for p in pkl_dir.glob("*.pkl"):
            try:
                p.unlink()
                deleted += 1
            except OSError:
                pass

    return {"pkl_deleted": deleted, "streamlit_cleared": True}
