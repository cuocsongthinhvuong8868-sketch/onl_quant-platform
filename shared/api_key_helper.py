"""
api_key_helper.py — Helper resolve shortcut API Key từ Streamlit Secrets.

Cách dùng trong bất kỳ tool page nào:
   from shared.api_key_helper import resolve_api_key
   
   raw = st.text_input("API Key (hoặc shortcut 4 số):", type="password")
   api_key, msg, is_error = resolve_api_key(raw)
   if is_error:
       st.error(msg)
   elif msg:
       st.success(msg)

Cấu hình Streamlit Secrets:
   AI_KEY_1234=sk-xxx...
   AI_KEY_5678=sk-yyy...
"""

import streamlit as st
import re


def resolve_api_key(raw_input: str, provider_key: str = ""):
    """
    Giải mã API Key từ shortcut hoặc key thật.

    Args:
        raw_input (str): Chuỗi người dùng nhập vào.

    Returns:
        tuple: (resolved_key: str, message: str, is_error: bool)
            - resolved_key:   API Key thật đã giải mã (hoặc raw_input nếu không phải shortcut)
            - message:        Thông báo hiển thị (rỗng nếu là key thật)
            - is_error:       True nếu shortcut không hợp lệ
    """
    raw_input = raw_input.strip() if raw_input else ""

    if not raw_input:
        return "", "", False

    # Kiểm tra nếu là 4 digit number -> shortcut
    if raw_input.isdigit() and len(raw_input) == 4:
        if provider_key == "kimi-2.6-local" and raw_input == "1234":
            return raw_input, "🔑 Đang dùng key local DS2API `1234`", False
        secret_name = f"AI_KEY_{raw_input}"
        try:
            resolved = st.secrets[secret_name]
            return resolved, f"🔑 Đã dùng shortcut `{raw_input}`", False
        except KeyError:
            return raw_input, f"❌ Shortcut `{raw_input}` không tồn tại trong Secrets", True
        except Exception as e:
            return raw_input, f"❌ Lỗi đọc Secrets: {e}", True

    # Key thật (sk-...)
    if raw_input.startswith("sk-"):
        return raw_input, "", False

    # Chuỗi không xác định
    return raw_input, "", False
