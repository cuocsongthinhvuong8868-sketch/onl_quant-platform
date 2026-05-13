import glob
import pathlib
import sys
import os

from config import DATA_LAKE

AI_PROVIDER_MAP = {
    "kimi-2.6": {
        "display": "Kimi 2.6",
    },
    "deepseek-v4-pro": {
        "display": "DeepSeek V4 Pro",
    },
}

def test_prefix(prefix):
    print(f"\n--- Testing prefix: {prefix} ---")
    _all_caches = sorted(
        list(DATA_LAKE.glob(f"daily_cache/{prefix}_*.txt")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    _all_caches = _all_caches[:10]
    if not _all_caches:
        print("  Chưa có dữ liệu phân tích lịch sử.")
    else:
        _options = {}
        for _fp in _all_caches:
            _fname = _fp.name
            _parts = _fname.replace(".txt", "").split("_")
            if len(_parts) >= 3:
                _date_str = _parts[-1]
                _provider_parts = _parts[1:-1]
                if prefix.count("_") > 0:
                    prefix_parts_count = len(prefix.split("_"))
                    _provider_parts = _parts[prefix_parts_count:-1]
                _provider = "_".join(_provider_parts)
                if len(_date_str) == 6 and _date_str.isdigit():
                    _date_display = f"{_date_str[:2]}/{_date_str[2:4]}/{_date_str[4:]}"
                    _provider_display = AI_PROVIDER_MAP.get(_provider, {}).get("display", _provider)
                    _label = f"{_date_display} — {_provider_display}"
                    _options[_label] = _fp
                else:
                    print(f"  FAILED DATE CHECK: {_fname} -> {_date_str}")
            else:
                print(f"  FAILED PARTS LENGTH: {_fname} -> len {len(_parts)}")
        
        if _options:
            print(f"  SUCCESS! Options count: {len(_options)}")
            for k, v in _options.items():
                print(f"    {k} -> {v.name}")
        else:
            print("  Không thể đọc được danh sách lịch sử.")

PREFIXES = [
    'dispersion',
    'esr_monitor',
    'feargreed',
    'manipulation',
    'market_breadth',
    'risk_adjusted_growth',
    'upside_ratio',
    'va_res',
    'var_cvar_vnindex'
]

for p in PREFIXES:
    test_prefix(p)
