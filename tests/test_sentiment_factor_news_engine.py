import importlib
import json
from datetime import datetime, timezone

from tools.sentiment_factor_news.core.classifier import classify_and_tag_item
from tools.sentiment_factor_news.core.aggregator import (
    bayesian_sentiment_posterior,
    build_window_feed,
)
from tools.sentiment_factor_news.core.normalizer import normalize_mozyfin, normalize_mozyfin_social, normalize_widata
from tools.sentiment_factor_news.core.scorer import score_item
from tools.sentiment_factor_news import report as sentiment_report
from tools.sentiment_factor_news.report import snapshot
from tools.sentiment_factor_news import config
from tools.sentiment_factor_news.connectors import mozyfin_connector


def test_default_fetch_limits_match_daily_ingestion_target(monkeypatch):
    monkeypatch.delenv("FETCH_LIMIT_MOZYFIN", raising=False)
    monkeypatch.delenv("FETCH_LIMIT_WIDATA", raising=False)

    reloaded = importlib.reload(config)

    assert reloaded.FETCH_LIMIT_MOZYFIN == 100
    assert reloaded.FETCH_LIMIT_MOZYFIN_SOCIAL == 100
    assert reloaded.FETCH_LIMIT_WIDATA == 500


def test_mozyfin_connector_skips_without_access_token(monkeypatch, tmp_path):
    monkeypatch.setattr(mozyfin_connector, "MOZYFIN_ACCESS_TOKEN", "")
    monkeypatch.setattr(mozyfin_connector, "MOZYFIN_API_KEY", "")
    monkeypatch.setattr(mozyfin_connector, "TOKEN_CACHE_FILE", tmp_path / "missing_token.txt")
    monkeypatch.delenv("MOZYFIN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("MOZYFIN_TOKEN", raising=False)
    monkeypatch.delenv("MOZYFIN_API_KEY", raising=False)
    monkeypatch.delenv("MOZYFIN_COOKIES_JSON", raising=False)

    assert mozyfin_connector.fetch_mozyfin_news(limit=10) == []


def test_mozyfin_connector_authorization_header(monkeypatch, tmp_path):
    monkeypatch.setattr(mozyfin_connector, "MOZYFIN_ACCESS_TOKEN", "abc123")
    monkeypatch.setattr(mozyfin_connector, "MOZYFIN_API_KEY", "")
    monkeypatch.setattr(mozyfin_connector, "TOKEN_CACHE_FILE", tmp_path / "missing_token.txt")
    monkeypatch.delenv("MOZYFIN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("MOZYFIN_TOKEN", raising=False)
    monkeypatch.delenv("MOZYFIN_API_KEY", raising=False)
    monkeypatch.delenv("MOZYFIN_COOKIES_JSON", raising=False)

    headers = mozyfin_connector._build_headers()

    assert headers["Authorization"] == "Bearer abc123"


def test_mozyfin_connector_api_key_header(monkeypatch, tmp_path):
    monkeypatch.setattr(mozyfin_connector, "MOZYFIN_ACCESS_TOKEN", "")
    monkeypatch.setattr(mozyfin_connector, "MOZYFIN_API_KEY", "key123")
    monkeypatch.setattr(mozyfin_connector, "MOZYFIN_AUTH_HEADER", "x-api-key")
    monkeypatch.setattr(mozyfin_connector, "TOKEN_CACHE_FILE", tmp_path / "missing_token.txt")
    monkeypatch.delenv("MOZYFIN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("MOZYFIN_TOKEN", raising=False)
    monkeypatch.delenv("MOZYFIN_API_KEY", raising=False)
    monkeypatch.delenv("MOZYFIN_AUTH_HEADER", raising=False)
    monkeypatch.delenv("MOZYFIN_COOKIES_JSON", raising=False)

    headers = mozyfin_connector._build_headers()

    assert headers["x-api-key"] == "key123"


def test_mozyfin_cookie_parser_accepts_github_secret_formats(monkeypatch):
    assert mozyfin_connector._cookies_to_dict({"name": "cookie_a", "value": "value_a"}) == {
        "cookie_a": "value_a"
    }
    assert mozyfin_connector._cookies_to_dict({"cookies": [{"name": "cookie_b", "value": "value_b"}]}) == {
        "cookie_b": "value_b"
    }
    assert mozyfin_connector._cookies_to_dict("cookie_c=value_c; cookie_d=value_d") == {
        "cookie_c": "value_c",
        "cookie_d": "value_d",
    }
    assert mozyfin_connector._cookies_to_dict(
        "MOZYFIN_COOKIES_JSON='[{\"name\":\"cookie_e\",\"value\":\"value_e\"}]'"
    ) == {"cookie_e": "value_e"}

    monkeypatch.setenv("MOZYFIN_COOKIE_NAME", "cookie_f")
    assert mozyfin_connector._cookies_to_dict("value_f") == {"cookie_f": "value_f"}


def test_mozyfin_limit_is_clamped_to_api_v2_maximum():
    assert mozyfin_connector._sanitize_news_limit(1000) == 100
    assert mozyfin_connector._sanitize_news_limit(0) == 1
    assert mozyfin_connector._sanitize_news_limit("bad") == 100


def test_mozyfin_social_fetch_uses_authorized_endpoint(monkeypatch, tmp_path):
    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"data": [{"id": "social-1", "headline_vi": "ok"}]}

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        assert url.endswith("/social-post")
        assert kwargs["headers"]["Authorization"] == "Bearer abc123"
        assert kwargs["params"] == {"limit": 100, "writing_track": "MARKET_INSIGHT"}
        return FakeResponse()

    monkeypatch.setattr(mozyfin_connector, "MOZYFIN_ACCESS_TOKEN", "abc123")
    monkeypatch.setattr(mozyfin_connector, "MOZYFIN_API_KEY", "")
    monkeypatch.setattr(mozyfin_connector, "TOKEN_CACHE_FILE", tmp_path / "missing_token.txt")
    monkeypatch.setattr(mozyfin_connector.requests, "get", fake_get)
    monkeypatch.delenv("MOZYFIN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("MOZYFIN_TOKEN", raising=False)
    monkeypatch.delenv("MOZYFIN_API_KEY", raising=False)
    monkeypatch.delenv("MOZYFIN_COOKIES_JSON", raising=False)

    rows = mozyfin_connector.fetch_mozyfin_social_posts(limit=1000, writing_track="MARKET_INSIGHT")

    assert rows == [{"id": "social-1", "headline_vi": "ok"}]


def test_mozyfin_fetch_uses_cookie_refresh_without_static_token(monkeypatch, tmp_path):
    token = "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjQxMDI0NDQ4MDB9.sig"
    calls = {"post": 0, "get": 0}

    class FakeResponse:
        def __init__(self, status_code=200, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise AssertionError(f"unexpected HTTP {self.status_code}")

    def fake_post(*args, **kwargs):
        calls["post"] += 1
        assert kwargs["headers"]["next-action"] == "action123"
        return FakeResponse(text=f"0:{token}")

    def fake_get(*args, **kwargs):
        calls["get"] += 1
        assert kwargs["headers"]["Authorization"] == f"Bearer {token}"
        assert kwargs["params"]["limit"] == 100
        return FakeResponse(payload={"data": [{"id": 1, "title": "ok"}]})

    monkeypatch.setattr(mozyfin_connector, "MOZYFIN_ACCESS_TOKEN", "")
    monkeypatch.setattr(mozyfin_connector, "MOZYFIN_API_KEY", "")
    monkeypatch.setattr(mozyfin_connector, "TOKEN_CACHE_FILE", tmp_path / "mozyfin_token.txt")
    monkeypatch.setattr(mozyfin_connector, "_detect_next_action_id", lambda: "action123")
    monkeypatch.setattr(mozyfin_connector.requests, "post", fake_post)
    monkeypatch.setattr(mozyfin_connector.requests, "get", fake_get)
    monkeypatch.delenv("MOZYFIN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("MOZYFIN_TOKEN", raising=False)
    monkeypatch.delenv("MOZYFIN_API_KEY", raising=False)
    monkeypatch.delenv("MOZYFIN_AUTH_HEADER", raising=False)
    monkeypatch.setenv("MOZYFIN_COOKIES_JSON", json.dumps([{"name": "session", "value": "abc"}]))

    assert mozyfin_connector.fetch_mozyfin_news(limit=1000) == [{"id": 1, "title": "ok"}]
    assert calls == {"post": 1, "get": 1}


def test_mozyfin_banking_news_scores_positive():
    raw_item = {
        "id": 1001,
        "title": "Cổ phiếu VCB bùng nổ, lợi nhuận ngân hàng cải thiện vượt bậc",
        "vi_summary": "Lợi nhuận ngân hàng tăng mạnh nhờ CASA cải thiện và tăng trưởng tín dụng tốt.",
        "source": "Mozyfin News",
        "published_date": "2026-06-14T03:00:00Z",
        "url": "https://mozyfin.com/news/1001",
        "sectors": ["banking-35"],
        "key_topics": ["economic", "stock"],
        "market_impact": "bullish",
        "entities": ["VCB"],
    }

    normalized = normalize_mozyfin(raw_item)
    classification = classify_and_tag_item(normalized)
    scores = score_item(normalized, classification)

    assert normalized["source_system"] == "mozyfin"
    assert classification["macro_channel"] == "banking_system"
    assert classification["sentiment_label"] == "positive"
    assert scores["final_score"] > 0.0


def test_mozyfin_v2_news_schema_normalizes_positive_sentiment():
    raw_item = {
        "id": "v2-1001",
        "headline_vi": "Tin ngan hang tich cuc",
        "summary_vi": "Thanh khoan va CASA cai thien.",
        "source": {"name": "Mozyfin"},
        "published_at": "2026-06-14T03:00:00Z",
        "url": "https://mozyfin.com/news/v2-1001",
        "sectors": [{"slug": "banking-35"}],
        "topics": [{"slug": "economic"}],
        "sentiment": "positive",
        "entities": [{"symbol": "VCB"}],
    }

    normalized = normalize_mozyfin(raw_item)

    assert normalized["title"] == "Tin ngan hang tich cuc"
    assert normalized["summary"] == "Thanh khoan va CASA cai thien."
    assert normalized["source_name"] == "Mozyfin"
    assert normalized["raw_topics"] == ["economic"]
    assert normalized["sectors"] == ["banking-35"]
    assert normalized["raw_impact"] == "bullish"
    assert normalized["entities"] == ["VCB"]


def test_mozyfin_social_post_scores_positive_with_lower_source_weight():
    fresh_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    raw_item = {
        "id": "social-1001",
        "sender_name": "QT Stocks",
        "headline_vi": "VN-Index breakout supports stock market risk appetite",
        "summary_vi": "Analysts are bullish as liquidity improves and banks lead the move.",
        "sentiment": "BULLISH",
        "writing_track": "MARKET_INSIGHT",
        "category": "stock market",
        "entities": ["SSI", "VCB"],
        "started_at": fresh_timestamp,
    }

    normalized = normalize_mozyfin_social(raw_item)
    classification = classify_and_tag_item(normalized)
    scores = score_item(normalized, classification)

    assert normalized["source_system"] == "mozyfin_social"
    assert normalized["source_name"] == "QT Stocks"
    assert normalized["raw_impact"] == "bullish"
    assert normalized["entities"] == ["SSI", "VCB"]
    assert classification["macro_channel"] == "risk_appetite"
    assert classification["sentiment_label"] == "positive"
    assert scores["source_weight"] == 0.55
    assert scores["final_score"] > 0.0


def test_widata_fx_pressure_scores_negative():
    raw_item = {
        "id": 2002,
        "title": "Tỷ giá USD/VND tăng mạnh áp lực lớn",
        "ai_translated_title": "Tỷ giá USD/VND tăng mạnh áp lực lớn",
        "ai_summary": "Tỷ giá tăng vượt mốc do chỉ số DXY tăng cao làm đồng VND mất giá mạnh.",
        "source": "WiData Signal",
        "publish_date": "2026-06-14T03:00:00Z",
        "url": "https://widata.vn/news/2002",
        "category": "Vĩ mô",
        "tag_level_0": "Tỷ giá",
        "tag_level_1": "USD/VND",
        "important_level": 2,
    }

    normalized = normalize_widata(raw_item)
    classification = classify_and_tag_item(normalized)
    scores = score_item(normalized, classification)

    assert normalized["source_system"] == "widata"
    assert classification["macro_channel"] == "fx_external"
    assert classification["event_type"] == "vnd_depreciation"
    assert scores["final_score"] < 0.0


def test_snapshot_reads_copied_feed():
    snap = snapshot(window="1d")

    assert snap["status"] == "ok"
    assert snap["window"] == "latest_1d"
    assert snap["news_count"] > 0
    assert "macro_composite" in snap


def test_sentiment_posterior_uses_reliability_as_likelihood_precision():
    reliable = [
        {
            "final_score": 0.20,
            "source_weight": 1.0,
            "confidence": 1.0,
            "time_decay": 1.0,
        }
    ]
    noisy = [
        {
            "final_score": 0.20,
            "source_weight": 0.2,
            "confidence": 0.5,
            "time_decay": 0.5,
        }
    ]

    reliable_post = bayesian_sentiment_posterior(reliable)
    noisy_post = bayesian_sentiment_posterior(noisy)

    assert reliable_post["posterior_mean"] > noisy_post["posterior_mean"]
    assert reliable_post["posterior_sd"] < noisy_post["posterior_sd"]
    assert reliable_post["prob_positive"] > noisy_post["prob_positive"]


def test_window_feed_exports_channel_and_macro_posteriors():
    feed = build_window_feed(
        [
            {
                "macro_channel": "liquidity",
                "final_score": 0.25,
                "source_weight": 0.9,
                "confidence": 0.8,
                "time_decay": 1.0,
                "source_system": "widata",
                "raw_category": "Vĩ mô",
                "entities": [],
                "title": "Liquidity improves",
                "summary": "",
            }
        ],
        "latest_1d",
        "2026-07-07T10:00:00+07:00",
    )

    assert "macro_composite_posterior" in feed
    assert "channel_posteriors" in feed
    assert feed["channel_posteriors"]["liquidity"]["active_count"] == 1
    assert feed["macro_composite_prob_pos"] == feed["macro_composite_posterior"]["prob_same_direction"]


def test_window_feed_counts_sources_dynamically():
    feed = build_window_feed(
        [
            {
                "macro_channel": "risk_appetite",
                "final_score": 0.12,
                "source_weight": 0.55,
                "confidence": 0.6,
                "time_decay": 1.0,
                "source_system": "mozyfin_social",
                "raw_category": "stock market",
                "entities": ["SSI"],
                "title": "Social post",
                "summary": "",
            },
            {
                "macro_channel": "liquidity",
                "final_score": 0.25,
                "source_weight": 0.85,
                "confidence": 0.8,
                "time_decay": 1.0,
                "source_system": "widata",
                "raw_category": "Vĩ mô",
                "entities": [],
                "title": "Liquidity improves",
                "summary": "",
            },
        ],
        "latest_1d",
        "2026-07-07T10:00:00+07:00",
    )

    assert feed["source_counts"] == {"mozyfin_social": 1, "widata": 1}


def test_report_formats_dynamic_source_counts():
    assert (
        sentiment_report._format_source_counts({"mozyfin_social": 2, "widata": 1})
        == "mozyfin_social=2, widata=1"
    )


def test_load_feed_backfills_legacy_posterior_fields(monkeypatch, tmp_path):
    feed_dir = tmp_path / "feed"
    feed_dir.mkdir()
    monkeypatch.setattr(sentiment_report, "FEED_DIR", feed_dir)

    legacy_feed = {
        "generated_at": "2026-07-07T08:00:00+07:00",
        "window": "latest_1d",
        "macro_composite": 0.0,
        "macro_composite_prob_pos": 0.5,
        "macro_composite_prob_positive": None,
        "regime": "neutral",
        "channel_scores": {"liquidity": 0.0},
        "channel_probs": {"liquidity": 0.5},
        "top_positive_drivers": [],
        "top_negative_drivers": [],
        "news_count": 1,
        "source_counts": {"widata": 1},
    }
    (feed_dir / "latest_1d.json").write_text(json.dumps(legacy_feed), encoding="utf-8")

    fresh_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    row = {
        "timestamp_utc": fresh_timestamp,
        "timestamp_vn": "2026-07-07T08:00:00+07:00",
        "macro_channel": "liquidity",
        "final_score": 0.25,
        "source_weight": 0.9,
        "confidence": 0.8,
        "time_decay": 1.0,
        "source_system": "widata",
        "source_name": "WiData",
        "raw_category": "Vĩ mô",
        "entities": [],
        "title": "Liquidity improves",
        "summary": "",
    }
    (feed_dir / "classified_news.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    feed = sentiment_report.load_feed("1d")

    assert feed["posterior_backfilled"] is True
    assert feed["channel_posteriors"]["liquidity"]["active_count"] == 1
    assert feed["channel_posteriors"]["liquidity"]["prob_positive"] > 0.5
    assert feed["channel_posteriors"]["liquidity"]["ci_95"] > 0.0
    assert feed["macro_composite_prob_positive"] > 0.5
