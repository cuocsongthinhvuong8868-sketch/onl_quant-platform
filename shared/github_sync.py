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
            # Dùng .get() để tránh KeyError
            token = st.secrets.get("GITHUB_TOKEN", "")
            if token:
                os.environ["GITHUB_TOKEN"] = token
        except Exception:
            pass
    return token


def _build_headers(token: str) -> dict:
    """Build headers cho GitHub API."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def test_connection() -> dict:
    """Test kết nối GitHub API và trả về thông tin token."""
    token = _get_token()
    if not token:
        return {"ok": False, "error": "GITHUB_TOKEN chưa được thiết lập."}

    # Test 1: Kiểm tra rate limit / auth
    r = requests.get(
        "https://api.github.com/user",
        headers=_build_headers(token),
        timeout=15,
    )
    if r.status_code != 200:
        try:
            msg = r.json().get("message", r.text)
        except Exception:
            msg = r.text
        return {"ok": False, "error": f"Auth test failed ({r.status_code}): {msg}"}

    user = r.json().get("login", "unknown")

    # Test 2: Kiểm tra quyền truy cập repo
    r2 = requests.get(
        f"{API_BASE}",
        headers=_build_headers(token),
        timeout=15,
    )
    if r2.status_code != 200:
        try:
            msg = r2.json().get("message", r2.text)
        except Exception:
            msg = r2.text
        return {"ok": False, "error": f"Repo access failed ({r2.status_code}): {msg}", "user": user}

    repo_info = r2.json()
    permissions = repo_info.get("permissions", {})

    return {
        "ok": True,
        "user": user,
        "repo": f"{OWNER}/{REPO}",
        "permissions": permissions,
        "can_push": permissions.get("push", False) or permissions.get("admin", False),
    }


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

    # Test kết nối trước
    conn = test_connection()
    if not conn["ok"]:
        raise RuntimeError(f"GitHub connection test failed: {conn['error']}")
    if not conn.get("can_push"):
        raise RuntimeError(
            f"Token của user '{conn['user']}' không có quyền ghi (push) vào repo {conn['repo']}. "
            "Vui lòng kiểm tra lại quyền của GitHub Token."
        )

    url = f"{API_BASE}/contents/{repo_path}"
    headers = _build_headers(token)

    # Lấy SHA nếu file đã tồn tại (để update thay vì create)
    sha = None
    resp = requests.get(url, headers=headers, params={"ref": BRANCH}, timeout=15)
    if resp.status_code == 200:
        sha = resp.json().get("sha")
    elif resp.status_code == 404:
        pass  # File chưa tồn tại, sẽ tạo mới
    else:
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

    data = resp.json()
    content = data.get("content", {})
    file_url = content.get("html_url", "")
    download_url = content.get("download_url", "")

    # Kiểm tra file thực sự có thể download được
    if download_url:
        check = requests.get(download_url, headers=headers, timeout=15)
        if check.status_code != 200:
            raise RuntimeError(
                f"GitHub PUT returned success nhưng file không tải được ({check.status_code}). "
                f"Có thể do cache CDN. URL: {file_url}"
            )

    return {
        "ok": True,
        "file_url": file_url,
        "download_url": download_url,
        "sha": content.get("sha", ""),
    }
