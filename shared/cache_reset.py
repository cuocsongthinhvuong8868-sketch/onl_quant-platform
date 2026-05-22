"""
shared/cache_reset.py — Helper xoá compute cache cho toàn bộ tool.

Hai layer:
  1. LOCAL: `reset_local_compute_caches()`
     - Clear `st.cache_data` (Streamlit in-memory cache toàn cục)
     - Xoá file `.pkl` trong `data_lake/daily_cache/` (compute pickle)

  2. REMOTE: `trigger_remote_cache_reset()`
     - Update `.github/triggers/run-command.json` qua GitHub REST API
       → fire workflow `command_runner.yml` → chạy `command/clear_daily_cache.py`
       → xóa pkl trên repo + commit về main → Streamlit Cloud rebuild

Cần GITHUB_TOKEN (Streamlit Secrets / env var) để dùng layer REMOTE.

KHÔNG xoá `.txt` AI cache (đắt $) và CSV raw data.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st

from config import DATA_LAKE
from shared.github_sync import API_BASE, BRANCH, _build_headers, _get_token


def reset_local_compute_caches() -> dict:
    """Clear local compute cache (Streamlit + on-disk pkl).

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


# Backwards-compat alias (used by older callers)
reset_all_compute_caches = reset_local_compute_caches


def trigger_remote_cache_reset() -> dict:
    """Fire workflow xóa pkl trên repo GitHub.

    Update trigger file `.github/triggers/run-command.json` qua REST API
    → push event → workflow command_runner.yml fire → chạy
    `command/clear_daily_cache.py` → xóa pkl + commit về main.

    Returns
    -------
    dict
        {"ok": True, "commit_url": str, "trigger_commit": str} on success
        {"ok": False, "error": str} on failure
    """
    token = _get_token()
    if not token:
        return {
            "ok": False,
            "error": "GITHUB_TOKEN chưa thiết lập (Streamlit Secrets hoặc env).",
        }

    trigger_path = ".github/triggers/run-command.json"
    url = f"{API_BASE}/contents/{trigger_path}"
    headers = _build_headers(token)

    resp = requests.get(url, headers=headers, params={"ref": BRANCH}, timeout=15)
    if resp.status_code != 200:
        return {
            "ok": False,
            "error": f"GET trigger SHA fail ({resp.status_code}): {resp.text[:200]}",
        }
    sha = resp.json().get("sha")

    new_payload = {
        "_comment": (
            "File này được Claude / Streamlit UI update qua REST API để trigger "
            "command_runner.yml. Mỗi lần content thay đổi → push event → workflow fire."
        ),
        "_schema": {
            "script_path": "Đường dẫn từ root repo, chỉ cho phép command/*.py",
            "args": "Extra args (optional)",
            "commit_outputs": "true → workflow commit data_lake/reports/docs về repo",
            "triggered_at": "ISO timestamp — force diff khi cùng script chạy lại",
        },
        "script_path": "command/clear_daily_cache.py",
        "args": "",
        "commit_outputs": True,
        "triggered_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    content_str = json.dumps(new_payload, indent=2, ensure_ascii=False) + "\n"

    put_resp = requests.put(
        url,
        headers=headers,
        json={
            "message": "Trigger: clear_daily_cache (user click reset button)",
            "content": base64.b64encode(content_str.encode("utf-8")).decode("ascii"),
            "branch": BRANCH,
            "sha": sha,
        },
        timeout=30,
    )
    if put_resp.status_code not in (200, 201):
        return {
            "ok": False,
            "error": f"PUT trigger fail ({put_resp.status_code}): {put_resp.text[:200]}",
        }

    commit = put_resp.json().get("commit", {})
    return {
        "ok": True,
        "commit_url": commit.get("html_url", ""),
        "trigger_commit": commit.get("sha", ""),
    }
