import os
import csv
import logging

logger = logging.getLogger(__name__)

def export_channel_scores_csv(scores: dict[str, float], counts: dict[str, int], window: str, generated_at: str, path: str):
    """
    Append or write the channel scores to a CSV file.
    Creates a new file with headers if it doesn't exist.
    """
    file_exists = os.path.exists(path)
    
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        with open(path, "a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["generated_at", "window", "channel", "score", "item_count"])
                
            for channel, score in scores.items():
                count = counts.get(channel, 0)
                writer.writerow([generated_at, window, channel, score, count])
                
        logger.info(f"Successfully updated CSV channel scores at {path}")
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
