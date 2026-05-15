"""
shared/history_selector.py — Helper hiển thị selectbox lịch sử AI analysis
cho tất cả tools. Đảm bảo sắp xếp ngày mới nhất lên đầu.
"""
from datetime import datetime
from pathlib import Path


def build_history_options(cache_files: list, prefix: str, provider_map: dict) -> dict:
    """Parse danh sách cache files thành dict {label: path}, sắp xếp ngày mới nhất trước.

    Args:
        cache_files: list of Path objects (đã glob)
        prefix: tên tool prefix (vd: "feargreed", "upside_ratio", "va_res")
        provider_map: AI_PROVIDER_MAP từ config

    Returns:
        OrderedDict-like dict {label: path} sắp theo ngày giảm dần
    """
    raw_options = []
    prefix_parts_count = len(prefix.split("_"))

    for fp in cache_files:
        fname = fp.name
        parts = fname.replace(".txt", "").split("_")
        if len(parts) < 3:
            continue
        date_str = parts[-1]
        if len(date_str) != 6 or not date_str.isdigit():
            continue

        provider_parts = parts[prefix_parts_count:-1]
        provider = "_".join(provider_parts)

        # Parse date cho sorting
        try:
            parsed_date = datetime.strptime(date_str, "%d%m%y")
        except ValueError:
            continue

        date_display = f"{date_str[:2]}/{date_str[2:4]}/{date_str[4:]}"
        provider_display = provider_map.get(provider, {}).get("display", provider)
        label = f"{date_display} — {provider_display}"

        raw_options.append((parsed_date, label, fp))

    # Sắp xếp theo ngày giảm dần (mới nhất trước)
    raw_options.sort(key=lambda x: x[0], reverse=True)

    return {label: path for _, label, path in raw_options}
