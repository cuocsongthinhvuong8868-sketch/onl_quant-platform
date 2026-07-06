from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATA_LAKE


SENTIMENT_DATA_DIR = DATA_LAKE / "sentiment_factor_news"
FEED_DIR = SENTIMENT_DATA_DIR / "feed"
WINDOWS = ("1d", "7d", "30d")


def _feed_path(window: str) -> Path:
    normalized = str(window or "1d").strip().lower()
    if normalized in {"latest", "default"}:
        return FEED_DIR / "latest.json"
    if normalized not in WINDOWS:
        normalized = "1d"
    return FEED_DIR / f"latest_{normalized}.json"


def load_feed(window: str = "1d") -> dict[str, Any]:
    path = _feed_path(window)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run python command/update_sentiment_factor_news.py")
    return json.loads(path.read_text(encoding="utf-8"))


def load_classified_news(limit: int | None = None) -> list[dict[str, Any]]:
    path = FEED_DIR / "classified_news.jsonl"
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    rows.sort(key=lambda item: item.get("timestamp_vn", ""), reverse=True)
    return rows[:limit] if limit else rows


def load_channel_scores() -> pd.DataFrame:
    path = FEED_DIR / "channel_scores.csv"
    if not path.exists():
        return pd.DataFrame(columns=["generated_at", "window", "channel", "score", "item_count"])
    return pd.read_csv(path)


def _top_channels(channel_scores: dict[str, Any], channel_probs: dict[str, Any] = None, n: int = 5, reverse: bool = True) -> list[dict[str, Any]]:
    rows = []
    for channel, value in (channel_scores or {}).items():
        try:
            score = float(value)
        except Exception:
            score = 0.0
        prob = float(channel_probs.get(channel, 0.5)) if channel_probs else 0.5
        rows.append({"channel": channel, "score": round(score, 4), "prob_pos": round(prob, 4)})
    rows.sort(key=lambda row: row["score"], reverse=reverse)
    return rows[:n]


def _format_driver(driver: dict[str, Any]) -> str:
    title = driver.get("title") or "N/A"
    channel = driver.get("macro_channel") or "unknown"
    score = driver.get("final_score")
    source = driver.get("source") or "N/A"
    timestamp = driver.get("timestamp") or "N/A"
    try:
        score_text = f"{float(score):+.3f}"
    except Exception:
        score_text = "N/A"
    return f"- {title} | channel={channel} | score={score_text} | source={source} | time={timestamp}"


def snapshot(df_close=None, load_custom=None, window: str = "1d") -> dict[str, Any]:
    try:
        feed = load_feed(window)
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "window": window,
            "generated_at": "",
            "macro_composite": 0.0,
            "regime": "N/A",
            "news_count": 0,
        }

    channel_scores = feed.get("channel_scores", {})
    channel_probs = feed.get("channel_probs", {})
    return {
        "status": "ok",
        "error": "",
        "generated_at": feed.get("generated_at", ""),
        "window": feed.get("window", window),
        "macro_composite": round(float(feed.get("macro_composite", 0.0)), 4),
        "macro_composite_prob_pos": round(float(feed.get("macro_composite_prob_pos", 0.5)), 4),
        "regime": feed.get("regime", "neutral"),
        "news_count": int(feed.get("news_count", 0) or 0),
        "source_counts": feed.get("source_counts", {}),
        "top_positive_channels": _top_channels(channel_scores, channel_probs, reverse=True),
        "top_negative_channels": _top_channels(channel_scores, channel_probs, reverse=False),
        "top_positive_drivers": feed.get("top_positive_drivers", [])[:5],
        "top_negative_drivers": feed.get("top_negative_drivers", [])[:5],
    }


def build_structured_report() -> str:
    blocks: list[str] = []
    for window in WINDOWS:
        snap = snapshot(window=window)
        if snap["status"] != "ok":
            blocks.append(f"=== Window {window} ===\nDATA INSUFFICIENT: {snap.get('error')}")
            continue

        source_counts = snap.get("source_counts", {})
        pos_channels = ", ".join(
            f"{row['channel']}={row['score']:+.3f}(P_conf:{row['prob_pos']:.0%})" for row in snap.get("top_positive_channels", [])
        )
        neg_channels = ", ".join(
            f"{row['channel']}={row['score']:+.3f}(P_conf:{row['prob_pos']:.0%})" for row in snap.get("top_negative_channels", [])
        )
        pos_drivers = "\n".join(_format_driver(item) for item in snap.get("top_positive_drivers", [])) or "- N/A"
        neg_drivers = "\n".join(_format_driver(item) for item in snap.get("top_negative_drivers", [])) or "- N/A"

        blocks.append(
            f"""=== Window {window} ===
Generated at: {snap['generated_at']}
Regime: {snap['regime']}
Macro composite: {snap['macro_composite']:+.4f} (Bayes Confidence: {snap.get('macro_composite_prob_pos', 0.5):.0%})
News count: {snap['news_count']}
Source counts: mozyfin={source_counts.get('mozyfin', 0)}, widata={source_counts.get('widata', 0)}
Top positive channels: {pos_channels}
Top negative channels: {neg_channels}

Top positive drivers:
{pos_drivers}

Top negative drivers:
{neg_drivers}"""
        )
    return "\n\n".join(blocks)


def build_sentiment_factor_news_ai_prompt() -> tuple[str, str]:
    system_prompt = (
        "You are a Vietnam macro/news sentiment analyst for an AI CIO. "
        "Use only the supplied rule-based news sentiment feed. "
        "Do not invent news, prices, or macro values. "
        "Treat this feed as a soft, fast-moving sentiment overlay, not a hard allocation rule. "
        "Answer in Vietnamese, concise and decision-useful."
    )
    user_prompt = f"""
# INPUT DATA

## Sentiment Factor From News Monitor
{build_structured_report()}

# REQUIRED OUTPUT
1. Nêu regime news sentiment hiện tại ở 1d, 7d, 30d. Sử dụng mức độ xác nhận tin cậy "Bayes Confidence" (P_conf) để làm Guardrail cho độ chắc chắn của kết luận:
   - P_conf > 85%: Bắt buộc dùng giọng điệu "Khẳng định chắc chắn" (Strongly Confirmed) theo hướng của Regime.
   - 65% < P_conf <= 85%: Dùng giọng điệu "Nghiêng về / Dấu hiệu ban đầu" (Leaning) theo hướng của Regime.
   - P_conf <= 65%: Bắt buộc dùng giọng điệu "Giằng co / Nhiễu loạn" (Inconclusive / Mixed Signals), tuyệt đối cấm kết luận xu hướng rõ ràng vì thông tin chưa đủ độ tin cậy.
2. Chỉ ra các channel đang kéo risk-on/risk-off mạnh nhất. Chú ý tới mức độ xác nhận tin cậy của kênh đó thông qua P_conf.
3. Tóm tắt 3-5 positive/negative drivers quan trọng, không bịa thêm tin ngoài input.
4. Kết luận tác động lên AI CIO: supports / conflicts / neutral với macro layer và market-internal tools.
5. Nêu caveat: source coverage, stale feed nếu generated_at cũ, và rủi ro headline noise.
""".strip()
    return system_prompt, user_prompt
