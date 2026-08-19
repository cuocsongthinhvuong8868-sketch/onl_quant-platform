from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMRoutePolicy:
    max_tokens: int
    thinking: bool = False


ROUTE_POLICIES: dict[str, LLMRoutePolicy] = {
    "auth_probe": LLMRoutePolicy(max_tokens=5, thinking=False),
    "child_report": LLMRoutePolicy(max_tokens=900, thinking=False),
    "executive_summary": LLMRoutePolicy(max_tokens=2_200, thinking=False),
    "chat": LLMRoutePolicy(max_tokens=1_400, thinking=False),
    "query_planner": LLMRoutePolicy(max_tokens=400, thinking=False),
    "language_repair": LLMRoutePolicy(max_tokens=900, thinking=False),
}


def is_deepseek_model(model: str | None) -> bool:
    return str(model or "").strip().lower().startswith("deepseek-")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def completion_options(
    *,
    model: str,
    route: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    thinking: bool | None = None,
) -> dict[str, Any]:
    """Return bounded provider-compatible options without collecting usage telemetry."""

    policy = ROUTE_POLICIES.get(route, ROUTE_POLICIES["child_report"])
    resolved_max_tokens = int(max_tokens or policy.max_tokens)
    resolved_thinking = policy.thinking if thinking is None else bool(thinking)
    if route == "executive_summary":
        resolved_thinking = _env_bool("DEEPSEEK_FINAL_THINKING", resolved_thinking)

    options: dict[str, Any] = {
        "model": model,
        "max_tokens": resolved_max_tokens,
    }
    if is_deepseek_model(model):
        options["extra_body"] = {
            "thinking": {"type": "enabled" if resolved_thinking else "disabled"}
        }
        if resolved_thinking:
            options["reasoning_effort"] = "high"
        elif temperature is not None:
            options["temperature"] = temperature
    elif temperature is not None:
        options["temperature"] = temperature
    return options
