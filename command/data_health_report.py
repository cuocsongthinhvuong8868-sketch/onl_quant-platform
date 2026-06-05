from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from src.data_manager import DataManager, format_cli_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a data_lake health report.")
    parser.add_argument("--format", choices=["text", "json", "csv"], default="text")
    parser.add_argument("--output", type=Path, help="Write json/csv report to this path.")
    args = parser.parse_args()

    manager = DataManager(root_dir=ROOT_DIR)
    report = manager.check_data_freshness()

    if args.output:
        if args.format == "text":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(format_cli_report(report), encoding="utf-8")
        else:
            manager.export_report(args.output, fmt=args.format)
        print(f"Wrote {args.output}")
        return 0

    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif args.format == "csv":
        import csv

        fieldnames = [
            "name",
            "category",
            "status",
            "latest_data_date",
            "freshness_days",
            "latest_file",
            "file_count",
            "status_reason",
        ]
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()
        for row in report["sources"]:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    else:
        print(format_cli_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

