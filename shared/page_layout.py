from __future__ import annotations

import os
from html import escape
from typing import Any

import streamlit as st


TONE_STYLES = {
    "positive": {
        "text": "#15803d",
        "border": "#22c55e",
        "bg": "#f0fdf4",
        "soft": "#dcfce7",
    },
    "warning": {
        "text": "#b45309",
        "border": "#f59e0b",
        "bg": "#fffbeb",
        "soft": "#fef3c7",
    },
    "danger": {
        "text": "#b91c1c",
        "border": "#ef4444",
        "bg": "#fef2f2",
        "soft": "#fee2e2",
    },
    "info": {
        "text": "#1d4ed8",
        "border": "#3b82f6",
        "bg": "#eff6ff",
        "soft": "#dbeafe",
    },
    "neutral": {
        "text": "#334155",
        "border": "#94a3b8",
        "bg": "#f8fafc",
        "soft": "#e2e8f0",
    },
}


GLOBAL_STYLE = """
<style>
.block-container {
    max-width: 96rem;
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}

div[data-testid="stMetric"] {
    min-height: 70px;
    overflow: visible;
}
div[data-testid="stMetric"] label,
div[data-testid="stMetric"] [data-testid="stMetricLabel"],
div[data-testid="stMetric"] [data-testid="stMetricValue"],
div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
    max-width: 100%;
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
    overflow-wrap: anywhere;
    word-break: break-word;
    line-height: 1.25;
}
div[data-testid="stMetric"] [data-testid="stMetricValue"] > div,
div[data-testid="stMetric"] [data-testid="stMetricDelta"] > div {
    white-space: normal !important;
    overflow-wrap: anywhere;
    word-break: break-word;
}

.oq-signal-card {
    width: 100%;
    box-sizing: border-box;
    border: 1px solid var(--oq-signal-border);
    border-left: 6px solid var(--oq-signal-border);
    border-radius: 8px;
    padding: 0.72rem 0.84rem;
    min-height: var(--oq-signal-min-height, 82px);
    background: var(--oq-signal-bg);
    overflow: visible;
}
.oq-signal-label {
    color: #475569;
    font-size: 0.78rem;
    font-weight: 700;
    line-height: 1.2;
    margin-bottom: 0.34rem;
    white-space: normal;
    overflow-wrap: anywhere;
}
.oq-signal-value {
    display: block;
    color: var(--oq-signal-text);
    font-size: 1.08rem;
    font-weight: 760;
    line-height: 1.24;
    white-space: normal;
    overflow: visible;
    overflow-wrap: anywhere;
    word-break: break-word;
}
.oq-signal-caption {
    margin-top: 0.4rem;
    color: #64748b;
    font-size: 0.82rem;
    line-height: 1.28;
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
}
.oq-signal-pill {
    display: inline-flex;
    align-items: center;
    max-width: 100%;
    box-sizing: border-box;
    padding: 0.18rem 0.52rem;
    border-radius: 999px;
    border: 1px solid var(--oq-signal-border);
    background: var(--oq-signal-soft);
    color: var(--oq-signal-text);
    font-size: 0.82rem;
    font-weight: 700;
    line-height: 1.24;
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
}
</style>
"""


def check_password() -> None:
    """
    Kiểm tra mật khẩu đăng nhập của người dùng.
    Nếu chưa đăng nhập, hiển thị form đăng nhập và dừng thực thi script.
    """
    configured_password = None

    # Thử lấy từ streamlit secrets
    try:
        if st.secrets:
            for key in ["LOGIN_PASSWORD", "login_password", "PASSWORD", "password"]:
                if key in st.secrets:
                    configured_password = str(st.secrets[key])
                    break
    except Exception:
        pass

    # Thử lấy từ biến môi trường (fall-back)
    if not configured_password:
        for key in ["LOGIN_PASSWORD", "PASSWORD"]:
            val = os.getenv(key)
            if val:
                configured_password = val
                break

    # Nếu chưa cấu hình mật khẩu ở bất kỳ đâu, hiển thị hướng dẫn thiết lập
    if not configured_password:
        st.warning("🔒 **Security Setup Required**")
        st.info(
            "Hệ thống yêu cầu mật khẩu đăng nhập nhưng chưa có mật khẩu nào được thiết lập.\n\n"
            "**Cách thiết lập:**\n"
            "1. **Chạy Local:** Tạo file `.streamlit/secrets.toml` trong thư mục gốc dự án và thêm:\n"
            "   ```toml\n"
            "   password = \"mat_khau_cua_ban\"\n"
            "   ```\n"
            "2. **Streamlit Cloud:** Vào cài đặt ứng dụng (App settings) -> **Secrets** và thêm:\n"
            "   ```toml\n"
            "   password = \"mat_khau_cua_ban\"\n"
            "   ```"
        )
        st.stop()

    # Nếu đã xác thực thành công trong session_state
    if st.session_state.get("authenticated") is True:
        # Hiển thị nút đăng xuất ở Sidebar cho tiện ích
        with st.sidebar:
            st.markdown("---")
            if st.button("🔒 Đăng xuất", key="logout_btn", use_container_width=True):
                st.session_state["authenticated"] = False
                st.rerun()
        return

    # Ẩn sidebar khi chưa đăng nhập
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] {
            display: none;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # Thêm CSS style cao cấp cho form đăng nhập
    st.markdown(
        """
        <style>
        .login-wrapper {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 2.5rem;
            max-width: 440px;
            margin: 5rem auto 1.5rem auto;
            background: rgba(255, 255, 255, 0.85);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border-radius: 16px;
            border: 1px solid rgba(226, 232, 240, 0.8);
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.05);
        }
        
        @media (prefers-color-scheme: dark) {
            .login-wrapper {
                background: rgba(30, 41, 59, 0.7);
                border: 1px solid rgba(255, 255, 255, 0.05);
                box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3), 0 10px 10px -10px rgba(0, 0, 0, 0.3);
            }
        }
        
        .login-logo {
            font-size: 3.5rem;
            margin-bottom: 1rem;
            display: inline-block;
            animation: pulse 2.5s infinite ease-in-out;
        }
        
        .login-title {
            font-size: 1.75rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
            background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-align: center;
        }
        
        .login-subtitle {
            font-size: 0.875rem;
            color: #64748b;
            margin-bottom: 2rem;
            text-align: center;
            line-height: 1.5;
        }
        
        @media (prefers-color-scheme: dark) {
            .login-subtitle {
                color: #94a3b8;
            }
        }
        
        /* Cấu hình Streamlit Form */
        div[data-testid="stForm"] {
            border: none !important;
            padding: 0 !important;
            background: transparent !important;
        }
        
        /* Cấu hình nút bấm đăng nhập */
        div[data-testid="stForm"] button[type="submit"] {
            background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%) !important;
            color: white !important;
            border: none !important;
            font-weight: 600 !important;
            padding: 0.75rem 1.5rem !important;
            border-radius: 8px !important;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
            width: 100% !important;
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.25) !important;
            cursor: pointer !important;
        }
        
        div[data-testid="stForm"] button[type="submit"]:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 6px 20px rgba(59, 130, 246, 0.35) !important;
            filter: brightness(1.05) !important;
        }
        
        div[data-testid="stForm"] button[type="submit"]:active {
            transform: translateY(0) !important;
        }
        
        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.08); }
            100% { transform: scale(1); }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # Hiển thị form đăng nhập căn giữa
    st.markdown(
        """
        <div class="login-wrapper">
            <div class="login-logo">📊</div>
            <div class="login-title">Quant Platform</div>
            <div class="login-subtitle">Hệ thống phân tích định lượng đa chiều.<br>Vui lòng nhập mật khẩu truy cập để tiếp tục.</div>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    col1, col2, col3 = st.columns([1, 4, 1])
    with col2:
        with st.form("login_form"):
            password_input = st.text_input(
                "Mật khẩu truy cập",
                type="password",
                placeholder="Nhập mật khẩu...",
                label_visibility="collapsed"
            )
            submitted = st.form_submit_button("Đăng nhập")
            
            if submitted:
                if password_input == configured_password:
                    st.session_state["authenticated"] = True
                    st.success("Đăng nhập thành công! Đang chuyển hướng...")
                    st.rerun()
                else:
                    st.error("Mật khẩu không chính xác. Vui lòng thử lại.")
    
    st.stop()


def setup_page(page_title: str) -> None:
    st.set_page_config(
        page_title=page_title,
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(GLOBAL_STYLE, unsafe_allow_html=True)

    # Kiểm tra mật khẩu đăng nhập trước khi hiển thị bất kỳ nội dung nào
    check_password()


def tone_for_signal(value: Any, default: str = "neutral") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default

    danger_words = (
        "stress", "critical", "cut", "tight", "pre-crash", "high stress",
        "đảo ngược", "rủi ro", "risk", "fire", "falsified", "bearish",
    )
    warning_words = (
        "warning", "elevated", "watch", "alert", "cảnh báo", "thắt chặt",
        "cao", "bẫy", "coupling", "anchoring", "leverage",
    )
    positive_words = (
        "add", "calm", "easy", "safe", "healthy", "accommodative",
        "low stress", "bình thường", "dốc lên", "dồi dào", "tích lũy",
        "tăng trưởng", "normal",
    )
    neutral_words = ("hold", "neutral", "trung tính", "sideway", "status quo", "monitor")

    if any(word in text for word in danger_words):
        return "danger"
    if any(word in text for word in warning_words):
        return "warning"
    if any(word in text for word in positive_words):
        return "positive"
    if any(word in text for word in neutral_words):
        return "neutral"
    return default


def _tone_style(tone: str | None, value: Any = None) -> dict[str, str]:
    resolved = tone or tone_for_signal(value)
    return TONE_STYLES.get(resolved, TONE_STYLES["neutral"])


def _style_vars(style: dict[str, str], min_height: int) -> str:
    return (
        f"--oq-signal-text:{style['text']};"
        f"--oq-signal-border:{style['border']};"
        f"--oq-signal-bg:{style['bg']};"
        f"--oq-signal-soft:{style['soft']};"
        f"--oq-signal-min-height:{int(min_height)}px;"
    )


def signal_card_html(
    label: Any,
    value: Any,
    *,
    tone: str | None = None,
    icon: str = "",
    caption: Any | None = None,
    min_height: int = 82,
) -> str:
    style = _tone_style(tone, value)
    label_text = escape(str(label))
    icon_text = f"{escape(str(icon))} " if icon else ""
    value_text = escape(str(value))
    caption_html = ""
    if caption is not None and str(caption).strip():
        caption_html = f'<div class="oq-signal-caption">{escape(str(caption))}</div>'
    return (
        f'<div class="oq-signal-card" style="{_style_vars(style, min_height)}">'
        f'<div class="oq-signal-label">{label_text}</div>'
        f'<div class="oq-signal-value">{icon_text}{value_text}</div>'
        f"{caption_html}"
        f"</div>"
    )


def render_signal_card(
    label: Any,
    value: Any,
    *,
    tone: str | None = None,
    icon: str = "",
    caption: Any | None = None,
    min_height: int = 82,
) -> None:
    st.markdown(
        signal_card_html(
            label,
            value,
            tone=tone,
            icon=icon,
            caption=caption,
            min_height=min_height,
        ),
        unsafe_allow_html=True,
    )


def signal_pill_html(value: Any, *, tone: str | None = None, icon: str = "") -> str:
    style = _tone_style(tone, value)
    icon_text = f"{escape(str(icon))} " if icon else ""
    return (
        f'<span class="oq-signal-pill" style="{_style_vars(style, 0)}">'
        f"{icon_text}{escape(str(value))}"
        f"</span>"
    )
