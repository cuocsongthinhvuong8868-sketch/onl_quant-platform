from shared.llm_policy import completion_options


def test_deepseek_chat_is_bounded_and_non_thinking(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_FINAL_THINKING", raising=False)

    options = completion_options(
        model="deepseek-v4-pro",
        route="chat",
        temperature=0.5,
    )

    assert options == {
        "model": "deepseek-v4-pro",
        "max_tokens": 1_400,
        "extra_body": {"thinking": {"type": "disabled"}},
        "temperature": 0.5,
    }


def test_deepseek_final_thinking_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_FINAL_THINKING", "true")

    options = completion_options(
        model="deepseek-v4-pro",
        route="executive_summary",
        temperature=0.5,
    )

    assert options["max_tokens"] == 2_200
    assert options["extra_body"] == {"thinking": {"type": "enabled"}}
    assert options["reasoning_effort"] == "high"
    assert "temperature" not in options


def test_non_deepseek_provider_keeps_standard_openai_options():
    options = completion_options(
        model="kimi-k3",
        route="child_report",
        temperature=1.0,
    )

    assert options == {
        "model": "kimi-k3",
        "max_tokens": 900,
        "temperature": 1.0,
    }
