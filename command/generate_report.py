"""
Generate one-shot quant snapshot report across tools.
Discovery rule: tools/<tool_name>/report.py with function snapshot(df_close, load_custom).
Output: reports/ddmmyy_quant_report.csv
"""
from __future__ import annotations

from datetime import datetime
from importlib import import_module
from pathlib import Path
import pandas as pd

from shared.data_loader import load_close_prices, load_custom


def _fail(tool: str, err: Exception) -> dict:
    return {"tool": tool, "snapshot_date": "", "status": "error", "error": str(err)}


def _ok(tool: str, payload: dict) -> dict:
    row = {"tool": tool, "snapshot_date": payload.get("snapshot_date", ""), "status": "ok", "error": ""}
    for k, v in payload.items():
        if k != "snapshot_date":
            row[k] = v
    return row


def discover_report_tools(root_dir: Path) -> list[str]:
    tools_dir = root_dir / "tools"
    names = []
    if not tools_dir.exists():
        return names
    for d in sorted(tools_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("__"):
            continue
        if (d / "report.py").exists():
            names.append(d.name)
    return names


def run_tool_snapshot(tool_name: str, df_close: pd.DataFrame) -> dict:
    module_path = f"tools.{tool_name}.report"
    mod = import_module(module_path)
    if not hasattr(mod, "snapshot"):
        raise AttributeError(f"{module_path} thiếu hàm snapshot(...)")
    payload = mod.snapshot(df_close, load_custom)
    if not isinstance(payload, dict):
        raise TypeError(f"{module_path}.snapshot phải trả về dict")
    return _ok(tool_name, payload)


def generate_report(output_dir: Path | None = None) -> Path:
    root = Path(__file__).resolve().parent.parent
    if output_dir is None:
        output_dir = Path.home() / "Desktop"

    df_close = load_close_prices()
    tools = discover_report_tools(root)

    rows = []
    for name in tools:
        try:
            rows.append(run_tool_snapshot(name, df_close))
        except Exception as e:
            rows.append(_fail(name, e))

    now = datetime.now()
    out = output_dir / f"{now.strftime('%d%m%y')}_quant_report.csv"

    report = pd.DataFrame(rows)
    report.insert(0, "generated_at", now.strftime("%Y-%m-%d %H:%M:%S"))
    report.to_csv(out, index=False)
    return out


if __name__ == "__main__":
    path = generate_report()
    print(path)
