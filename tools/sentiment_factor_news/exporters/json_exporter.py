import json
import os
import logging

logger = logging.getLogger(__name__)

def export_latest_json(feed: dict, path: str):
    """Export the summary feed to a JSON file."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(feed, f, ensure_ascii=False, indent=2)
        logger.info(f"Successfully exported JSON feed to {path}")
    except Exception as e:
        logger.error(f"Error exporting JSON feed: {e}")

def export_classified_jsonl(items: list[dict], path: str):
    """
    Append new classified items to the JSONL file.
    Only add if the line is not already present (checks news_id).
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        existing_ids = set()
        existing_lines = []
        
        # Read existing items to avoid duplicates in JSONL
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            obj = json.loads(line)
                            if "news_id" in obj:
                                existing_ids.add(obj["news_id"])
                            existing_lines.append(line)
                        except Exception:
                            pass
                            
        # Filter new items and format them
        new_lines = []
        for item in items:
            if item["news_id"] not in existing_ids:
                new_lines.append(json.dumps(item, ensure_ascii=False))
                
        # Append only new ones
        if new_lines:
            with open(path, "a", encoding="utf-8") as f:
                for line in new_lines:
                    f.write(line + "\n")
            logger.info(f"Appended {len(new_lines)} new items to {path}")
        else:
            logger.info(f"No new items to append to {path}")
            
    except Exception as e:
        logger.error(f"Error exporting JSONL: {e}")

def export_manifest_json(files: list[str], path: str, generated_at: str):
    """Export manifest.json listing all feed files."""
    manifest = {
        "feed_version": "1.0.0",
        "generated_at": generated_at,
        "files": files,
        "schema_version": "macro_sentiment_schema_v1"
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        logger.info(f"Successfully exported manifest.json to {path}")
    except Exception as e:
        logger.error(f"Error exporting manifest: {e}")
