import os
import sys
import json
import argparse
import time
import logging
from datetime import datetime, timezone, timedelta

# Import config
from tools.sentiment_factor_news import config

# Import connectors
from tools.sentiment_factor_news.connectors.mozyfin_connector import fetch_mozyfin_news, fetch_mozyfin_social_posts
from tools.sentiment_factor_news.connectors.widata_connector import fetch_widata_signals

# Import core modules
from tools.sentiment_factor_news.core.normalizer import normalize_item
from tools.sentiment_factor_news.core.dedup import load_history, save_history, dedup_filter, update_history_with_items
from tools.sentiment_factor_news.core.classifier import classify_and_tag_item
from tools.sentiment_factor_news.core.scorer import score_item
from tools.sentiment_factor_news.core.aggregator import filter_items_by_window, build_window_feed, calculate_channel_scores
from tools.sentiment_factor_news.exporters.json_exporter import export_latest_json, export_classified_jsonl, export_manifest_json
from tools.sentiment_factor_news.exporters.csv_exporter import export_channel_scores_csv
from tools.sentiment_factor_news.exporters.git_publisher import publish_feed

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOGS_DIR / "engine.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("market_sentiment_engine")




def run_ingestion(args):
    """
    Executes a single cycle of the feed engine ingestion, normalizer, 
    classifier, scorer, aggregator, and exporter.
    """
    logger.info("Starting ingestion cycle...")
    
    # 1. Fetch raw items
    raw_mozyfin = []
    raw_mozyfin_social = []
    raw_widata = []
    
    mozyfin_limit = args.limit_mozyfin or config.FETCH_LIMIT_MOZYFIN
    mozyfin_social_limit = getattr(args, "limit_mozyfin_social", None) or config.FETCH_LIMIT_MOZYFIN_SOCIAL
    widata_limit = args.limit_widata or config.FETCH_LIMIT_WIDATA
    social_track = getattr(args, "social_track", None) or None
    
    if args.source in ["all", "mozyfin"]:
        logger.info("Fetching Mozyfin news...")
        raw_mozyfin = fetch_mozyfin_news(limit=mozyfin_limit)

    if args.source in ["all", "mozyfin_social"]:
        logger.info("Fetching Mozyfin social posts...")
        raw_mozyfin_social = fetch_mozyfin_social_posts(
            limit=mozyfin_social_limit,
            writing_track=social_track,
        )
        
    if args.source in ["all", "widata"]:
        logger.info("Fetching WiData signals...")
        raw_widata = fetch_widata_signals(limit=widata_limit)
        
    # Archive raw items
    time_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    if raw_mozyfin:
        with open(config.DATA_DIR / "raw" / f"raw_mozyfin_{time_suffix}.json", "w", encoding="utf-8") as f:
            json.dump(raw_mozyfin, f, ensure_ascii=False, indent=2)
    if raw_mozyfin_social:
        with open(config.DATA_DIR / "raw" / f"raw_mozyfin_social_{time_suffix}.json", "w", encoding="utf-8") as f:
            json.dump(raw_mozyfin_social, f, ensure_ascii=False, indent=2)
    if raw_widata:
        with open(config.DATA_DIR / "raw" / f"raw_widata_{time_suffix}.json", "w", encoding="utf-8") as f:
            json.dump(raw_widata, f, ensure_ascii=False, indent=2)
            
    # 2. Normalize
    normalized_items = []
    for item in raw_mozyfin:
        try:
            normalized_items.append(normalize_item(item, "mozyfin"))
        except Exception as e:
            logger.error(f"Error normalizing Mozyfin item {item.get('id')}: {e}")

    for item in raw_mozyfin_social:
        try:
            normalized_items.append(normalize_item(item, "mozyfin_social"))
        except Exception as e:
            logger.error(f"Error normalizing Mozyfin social item {item.get('id')}: {e}")
            
    for item in raw_widata:
        try:
            normalized_items.append(normalize_item(item, "widata"))
        except Exception as e:
            logger.error(f"Error normalizing WiData item {item.get('id')}: {e}")
            
    # Archive normalized items
    if normalized_items:
        with open(config.DATA_DIR / "normalized" / f"norm_{time_suffix}.json", "w", encoding="utf-8") as f:
            json.dump(normalized_items, f, ensure_ascii=False, indent=2)
            
    # 3. Load dedup history and filter duplicates
    history = load_history()
    new_items = dedup_filter(normalized_items, history)
    logger.info(f"Filtered duplicates: {len(normalized_items)} input -> {len(new_items)} new items")
    
    # 4. Classify and Score new items
    classified_items = []
    for item in new_items:
        try:
            # Classify tags
            classification = classify_and_tag_item(item)
            
            # Scorer calculation
            scores = score_item(item, classification)
            
            # Combine into ClassifiedNewsItem
            classified_item = {**item, **classification, **scores}
            classified_items.append(classified_item)
        except Exception as e:
            logger.error(f"Error classifying/scoring item {item.get('news_id')}: {e}", exc_info=True)
            
    # Archive classified items
    if classified_items:
        with open(config.DATA_DIR / "classified" / f"class_{time_suffix}.json", "w", encoding="utf-8") as f:
            json.dump(classified_items, f, ensure_ascii=False, indent=2)
            
    # 5. Export classified news items to JSONL
    feed_jsonl_path = config.DATA_DIR / "feed" / "classified_news.jsonl"
    export_classified_jsonl(classified_items, str(feed_jsonl_path))
    
    # 6. Load ALL historical classified items to calculate rolling window feeds accurately
    all_classified = []
    if os.path.exists(feed_jsonl_path):
        with open(feed_jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        all_classified.append(json.loads(line))
                    except Exception:
                        pass
                        
    # 7. Generate rolling window feeds
    vn_tz = timezone(timedelta(hours=7))
    generated_at_vn = datetime.now(vn_tz).strftime("%Y-%m-%dT%H:%M:%S+07:00")
    
    # Latest 1d window (Last Day)
    items_1d = filter_items_by_window(all_classified, 24 * 60)
    feed_1d = build_window_feed(items_1d, "latest_1d", generated_at_vn)
    export_latest_json(feed_1d, str(config.DATA_DIR / "feed" / "latest_1d.json"))
    
    # Latest 7d window (Last 7 Days)
    items_7d = filter_items_by_window(all_classified, 7 * 24 * 60)
    feed_7d = build_window_feed(items_7d, "latest_7d", generated_at_vn)
    export_latest_json(feed_7d, str(config.DATA_DIR / "feed" / "latest_7d.json"))
    
    # Latest 30d window (Last 30 Days)
    items_30d = filter_items_by_window(all_classified, 30 * 24 * 60)
    feed_30d = build_window_feed(items_30d, "latest_30d", generated_at_vn)
    export_latest_json(feed_30d, str(config.DATA_DIR / "feed" / "latest_30d.json"))
    
    # Default latest.json is a copy of latest_1d.json
    export_latest_json(feed_1d, str(config.DATA_DIR / "feed" / "latest.json"))
    
    # 8. Export manifest.json
    export_manifest_json(
        files=[
            "latest.json",
            "latest_1d.json",
            "latest_7d.json",
            "latest_30d.json",
            "classified_news.jsonl",
            "channel_scores.csv"
        ],
        path=str(config.DATA_DIR / "feed" / "manifest.json"),
        generated_at=generated_at_vn
    )
    
    # 9. Append to CSV timeline
    csv_path = config.DATA_DIR / "feed" / "channel_scores.csv"
    
    # Calculate item counts per channel for CSV timeline
    def get_counts(items):
        counts = {}
        for item in items:
            ch = item.get("macro_channel", "unknown")
            counts[ch] = counts.get(ch, 0) + 1
        return counts
        
    counts_1d = get_counts(items_1d)
    counts_7d = get_counts(items_7d)
    counts_30d = get_counts(items_30d)
    
    export_channel_scores_csv(
        scores=feed_1d["channel_scores"],
        counts=counts_1d,
        window="latest_1d",
        generated_at=generated_at_vn,
        path=str(csv_path)
    )
    
    export_channel_scores_csv(
        scores=feed_7d["channel_scores"],
        counts=counts_7d,
        window="latest_7d",
        generated_at=generated_at_vn,
        path=str(csv_path)
    )
    
    export_channel_scores_csv(
        scores=feed_30d["channel_scores"],
        counts=counts_30d,
        window="latest_30d",
        generated_at=generated_at_vn,
        path=str(csv_path)
    )

    
    # 10. Update dedup history database
    history = update_history_with_items(new_items, history)
    save_history(history)
    
    # 11. Git Publish
    if args.publish_git:
        publish_feed(
            repo_path=config.FEED_REPO_PATH,
            branch=config.GIT_BRANCH,
            remote=config.GIT_REMOTE_NAME
        )
        
    logger.info("Ingestion cycle completed successfully.")


def main():
    parser = argparse.ArgumentParser(description="Market Sentiment Feed Engine")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--loop", type=int, default=0, help="Run every N minutes (0 = do not loop)")
    parser.add_argument(
        "--source",
        choices=["all", "mozyfin", "mozyfin_social", "widata"],
        default="all",
        help="Data source to fetch",
    )
    parser.add_argument("--publish-git", action="store_true", help="Commit and push changes to remote git repository")
    parser.add_argument("--limit-mozyfin", type=int, default=None, help="Override Mozyfin limit")
    parser.add_argument("--limit-mozyfin-social", type=int, default=None, help="Override Mozyfin social-post limit")
    parser.add_argument("--limit-widata", type=int, default=None, help="Override WiData limit")
    parser.add_argument("--social-track", type=str, default=None, help="Optional Mozyfin social writing_track filter")
    args = parser.parse_args()


    # Ingestion actions
    if args.loop > 0:
        logger.info(f"Running in loop mode. Ingestion runs every {args.loop} minutes. Press Ctrl+C to terminate.")
        while True:
            try:
                run_ingestion(args)
            except Exception as e:
                logger.error(f"Unhandled error in loop run: {e}", exc_info=True)
            logger.info(f"Sleeping for {args.loop} minutes...")
            time.sleep(args.loop * 60)
    else:
        run_ingestion(args)


if __name__ == "__main__":
    main()
