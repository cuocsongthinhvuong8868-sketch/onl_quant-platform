"""
command/clear_daily_cache.py — Xóa toàn bộ pkl trong data_lake/daily_cache/.

Mục đích: khi user click nút "Xử lý lại tính toán" trên Streamlit UI,
Streamlit gọi GitHub API cập nhật trigger file → workflow command_runner.yml
chạy script này → pkl bị xóa + commit về repo → Cloud rebuild → tools recompute
từ đầu.

KHÔNG xóa .txt AI cache (đắt $) và CSV raw data.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data_lake" / "daily_cache"


def main() -> int:
    if not CACHE_DIR.exists():
        print(f"⚠️  Cache dir không tồn tại: {CACHE_DIR}")
        return 0

    deleted = 0
    for p in CACHE_DIR.glob("*.pkl"):
        p.unlink()
        print(f"  ❌ Deleted: {p.name}")
        deleted += 1

    print(f"\n✅ Total deleted: {deleted} pkl file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
