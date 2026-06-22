import shared.page_layout as page_layout


def test_requires_login_bypasses_loopback(monkeypatch):
    monkeypatch.delenv("QUANT_PLATFORM_REQUIRE_LOGIN", raising=False)
    monkeypatch.delenv("STREAMLIT_RUNTIME_ENV", raising=False)
    monkeypatch.setattr(page_layout, "_get_request_host", lambda: "localhost")

    assert page_layout._requires_login() is False


def test_requires_login_on_streamlit_cloud_host(monkeypatch):
    monkeypatch.delenv("QUANT_PLATFORM_REQUIRE_LOGIN", raising=False)
    monkeypatch.setattr(page_layout, "_get_request_host", lambda: "quant-platform.streamlit.app")

    assert page_layout._requires_login() is True


def test_requires_login_defaults_true_for_unknown_host(monkeypatch):
    monkeypatch.delenv("QUANT_PLATFORM_REQUIRE_LOGIN", raising=False)
    monkeypatch.setattr(page_layout, "_get_request_host", lambda: "192.168.1.20")

    assert page_layout._requires_login() is True


def test_requires_login_env_override(monkeypatch):
    monkeypatch.setenv("QUANT_PLATFORM_REQUIRE_LOGIN", "false")
    monkeypatch.setattr(page_layout, "_get_request_host", lambda: "quant-platform.streamlit.app")

    assert page_layout._requires_login() is False
