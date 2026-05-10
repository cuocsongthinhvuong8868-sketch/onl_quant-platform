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

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
OWNER = os.getenv("GITHUB_REPO_OWNER", "cuocsongthinhvuong8868-sketch")
REPO = os.getenv("GITHUB_REPO_NAME", "onl_quant-platform")
BRANCH = os.getenv("GITHUB_BRANCH", "main")

API_BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"


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
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN chưa được thiết lập.")

    url = f"{API_BASE}/contents/{repo_path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Lấy SHA nếu file đã tồn tại (để update thay vì create)
    sha = None
    resp = requests.get(url, headers=headers, params={"ref": BRANCH}, timeout=15)
    if resp.status_code == 200:
        sha = resp.json().get("sha")

    payload = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("ascii"),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha

    resp = requests.put(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()
