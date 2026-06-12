"""
Copy/sanitize MozyFin JSON feeds for Risk-Adjusted Growth.

Usage:
  python command/update_risk_adjusted_growth_statistics.py
  python command/update_risk_adjusted_growth_statistics.py --source-dir /path/to/json
  python command/update_risk_adjusted_growth_statistics.py --financial-report-source-dir /path/to/bctc/json
"""
import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.risk_adjusted_growth.quant.data_prep import (
    FINANCIAL_REPORT_JSON_DIR,
    RAG_BANK_UNIVERSE,
    STATISTICS_JSON_DIR,
    copy_financial_report_json_feed,
    copy_statistics_json_feed,
    load_statistics_ratio_table,
    risk_adjusted_growth_source_signature,
)

DEFAULT_SOURCE_DIR = Path("/Users/macos/Desktop/bctc-scrape/Statistics/json")
DEFAULT_FINANCIAL_REPORT_SOURCE_DIR = Path("/Users/macos/Desktop/bctc-scrape/BCTC/json")


def main():
    parser = argparse.ArgumentParser(
        description="Update Risk-Adjusted Growth statistics JSON feed"
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--dest-dir", type=Path, default=STATISTICS_JSON_DIR)
    parser.add_argument(
        "--financial-report-source-dir",
        type=Path,
        default=DEFAULT_FINANCIAL_REPORT_SOURCE_DIR,
    )
    parser.add_argument(
        "--financial-report-dest-dir",
        type=Path,
        default=FINANCIAL_REPORT_JSON_DIR,
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Copy raw JSON instead of sanitized ratio-only JSON.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Copy all JSON files. Default is the Risk-Adjusted Growth bank universe only.",
    )
    args = parser.parse_args()

    universe = None if args.all else RAG_BANK_UNIVERSE
    count = copy_statistics_json_feed(
        args.source_dir,
        args.dest_dir,
        sanitize=not args.raw,
        universe=universe,
    )
    report_count = copy_financial_report_json_feed(
        args.financial_report_source_dir,
        args.financial_report_dest_dir,
        sanitize=not args.raw,
        universe=universe,
    )
    df = load_statistics_ratio_table(
        args.dest_dir,
        financial_report_dir=args.financial_report_dest_dir,
        universe=universe,
    )
    logger.info("Copied %d Statistics JSON files into %s", count, args.dest_dir)
    logger.info(
        "Copied %d financial report JSON files into %s",
        report_count,
        args.financial_report_dest_dir,
    )
    logger.info("Built bank statistics ratio table: %d valid tickers", len(df))
    logger.info(
        "Source signature: %s",
        risk_adjusted_growth_source_signature(args.dest_dir, args.financial_report_dest_dir),
    )


if __name__ == "__main__":
    main()
