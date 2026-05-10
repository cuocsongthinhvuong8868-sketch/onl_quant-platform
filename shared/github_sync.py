"""
Upload file lên GitHub repo qua REST API.
Dùng cho việc đồng bộ cache báo cáo AI CIO từ Streamlit Cloud về GitHub.

Cần thiết lập:
- GitHub Secret: GITHUB_TOKEN (classic token với quyền repo)
- Streamlit Secret: [secrets] GITHUB_TOKEN = "..."
"""
import os
import base64
import requests

OWNER = os.getenv("GITHUB_REPO_OWNER", "cuocsongthinhvuong8868-sketch")
REPO = os.getenv("GITHUB_REPO_NAME", "onl_quant-platform")
BRANCH = os.getenv("GITHUB_BRANCH", "main")

API_BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"


def _get_token() -> str:
    """Đọc token từ env mỗi lần gọi (không cache ở import time)."""
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        # Thử đọc từ streamlit secrets nếu có
        try:
            import streamlit as st
            token = st.secrets.get("GITHUB_TOKEN", "")
            if token:
                os.environ["GITHUB_TOKEN"] = token
        except Exception:
            pass
    return token


def upload_file(repo_path: str, content_bytes: bytes, message: str) -> dict:
    """
    Create hoặc update file trên GitHub.
    
    Parameters
    ----------
    repo_path : str
        Path trong repo, ví dụ: "data_lake/daily_cache/executive_summary_100526.txt"
    content_bytes : bytes
        Nội dung file (đã encode UTF-8 nếu là text)
    message : str
        Commit message
    
    Returns
    -------
    dict : JSON response từ GitHub API
    """
    token = _get_token()
    if not token:
        raise ValueError("GITHUB_TOKEN chưa được thiết lập. Vui lòng thêm vào Streamlit Secrets hoặc environment variable.")

    url = f"{API_BASE}/contents/{repo_path}"
    # Hỗ trợ cả classic token (token) và fine-grained token (Bearer)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Lấy SHA nếu file đã tồn tại (để update thay vì create)
    sha = None
    resp = requests.get(url, headers=headers, params={"ref": BRANCH}, timeout=15)
    if resp.status_code == 200:
        sha = resp.json().get("sha")
    elif resp.status_code == 404:
        pass  # File chưa tồn tại, sẽ tạo mới
    else:
        # Log lỗi GET để debug
        try:
            err_body = resp.json().get("message", resp.text)
        except Exception:
            err_body = resp.text
        raise RuntimeError(f"GitHub GET failed ({resp.status_code}): {err_body}")

    payload = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("ascii"),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha

    resp = requests.put(url, headers=headers, json=payload, timeout=30)
    if resp.status_code not in (200, 201):
        try:
            err_body = resp.json().get("message", resp.text)
        except Exception:
            err_body = resp.text
        raise RuntimeError(f"GitHub PUT failed ({resp.status_code}): {err_body}")
    return resp.json()
