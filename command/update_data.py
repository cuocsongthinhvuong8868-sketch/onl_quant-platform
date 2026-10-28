"""
update_data.py — Script cập nhật dữ liệu hằng ngày (Smart Incremental).

Luồng:
    1. Đọc danh sách mã từ tickers.csv
    2. Nếu market_data.csv đã tồn tại → incremental (chỉ tải ngày mới)
    3. Nếu chưa có hoặc --backfill → tải toàn bộ lookback
    4. Gộp thành 1 DataFrame (index=ngày, columns=mã)
    5. Lưu vào data_lake/market_data.csv

Usage:
    python command/update_data.py                    # incremental (default)
    python command/update_data.py --backfill 2190    # backfill ~6 năm
    python command/update_data.py --from-date 2019-01-01
"""
import os
import time
import logging
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Ép import config ở ROOT project thay vì command/config.py
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import (
    VNSTOCK_API_KEY,
    DATA_LAKE,
    MARKET_DATA,
    MARKET_VOLUME,
    VNINDEX_DATA,
    VN30_DATA,
    TICKERS_FILE,
    DEFAULT_LOOKBACK_DAYS,
)

if not VNSTOCK_API_KEY:
    api_key_file = Path.home() / ".vnstock" / "api_key.json"
    if api_key_file.exists():
        try:
            import json
            with open(api_key_file, "r") as f:
                data = json.load(f)
                VNSTOCK_API_KEY = data.get("api_key", "")
        except Exception:
            pass

if VNSTOCK_API_KEY:
    os.environ["VNSTOCK_API_KEY"] = VNSTOCK_API_KEY
    try:
        from vnstock.core import setup_api_key
        setup_api_key(VNSTOCK_API_KEY)
    except Exception:
        pass
    try:
        import vnai
        vnai.setup_api_key(VNSTOCK_API_KEY)
    except Exception:
        pass


class SafeRateLimiter:
    """
    Bộ điều tiết tốc độ gọi API để không chạm trần Rate Limit (60 req/phút của Community tier,
    hoặc 20 req/phút của Guest tier) và tự động phục hồi khi bị vượt hạn mức.
    """
    def __init__(self, max_requests_per_minute: int = 45, min_interval_seconds: float = 1.35):
        self.max_requests_per_minute = max_requests_per_minute
        self.min_interval_seconds = min_interval_seconds
        self.timestamps: list[float] = []
        self.last_call_time: float = 0.0

    def wait_if_needed(self) -> None:
        now = time.time()
        # 1. Giãn cách tối thiểu giữa 2 request liên tiếp
        elapsed = now - self.last_call_time
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
            now = time.time()

        # 2. Xóa các request ngoài cửa sổ 60 giây
        self.timestamps = [t for t in self.timestamps if now - t < 60.0]

        # 3. Nếu số request trong 60 giây đạt ngưỡng an toàn, chủ động sleep
        if len(self.timestamps) >= self.max_requests_per_minute:
            oldest = self.timestamps[0]
            sleep_time = max(1.0, 60.0 - (now - oldest) + 1.0)
            logger.info(
                "⏳ [Rate Limiter] Đạt %d requests trong 60s (ngưỡng an toàn %d). Tạm dừng %.1fs...",
                len(self.timestamps),
                self.max_requests_per_minute,
                sleep_time,
            )
            time.sleep(sleep_time)
            now = time.time()
            self.timestamps = [t for t in self.timestamps if now - t < 60.0]

        self.timestamps.append(time.time())
        self.last_call_time = time.time()

    def handle_rate_limit_exceeded(self, retry_after: float | None = None) -> None:
        """Khi bị vnstock/vnai chặn rate limit: ngủ đủ thời gian để reset hoàn toàn cửa sổ 60s."""
        wait_seconds = float(retry_after) if (retry_after and retry_after > 0) else 65.0
        wait_seconds = max(wait_seconds, 65.0)
        logger.warning(
            "⚠️ [Rate Limit] vnstock/vnai yêu cầu tạm dừng. Đang đợi %.0f giây để hạn mức làm mới...",
            wait_seconds,
        )
        time.sleep(wait_seconds)
        self.timestamps.clear()
        self.last_call_time = time.time()


def _init_rate_limiter() -> SafeRateLimiter:
    rpm = 45
    min_interval = 1.35
    try:
        import vnai
        tier_info = vnai.get_user_tier()
        limit_min = tier_info.get("limits", {}).get("per_minute", 60)
        if limit_min <= 20:
            rpm = 15
            min_interval = 4.0
        elif limit_min <= 60:
            rpm = 45
            min_interval = 1.35
        else:
            rpm = min(120, int(limit_min * 0.75))
            min_interval = round(60.0 / rpm, 2)
        logger.info(
            "Rate Limiter khởi tạo: Tier=%s, Giới hạn an toàn=%d req/phút, Giãn cách tối thiểu=%.2fs",
            tier_info.get("tier", "free"),
            rpm,
            min_interval,
        )
    except Exception as e:
        logger.debug("Không thể lấy tier info từ vnai: %s — dùng mặc định 45 req/phút", e)
    return SafeRateLimiter(max_requests_per_minute=rpm, min_interval_seconds=min_interval)


rate_limiter = _init_rate_limiter()


def _is_rate_limit_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    keywords = ("ratelimit", "rate limit", "60", "giới hạn", "too many requests", "429", "quota")
    return any(k in name or k in msg for k in keywords)


def _extract_retry_after(exc: Exception) -> float | None:
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        try:
            return float(retry_after)
        except (ValueError, TypeError):
            pass
    return None


def load_tickers() -> list:
    """Đọc danh sách mã từ tickers.csv."""
    try:
        tickers = (
            pd.read_csv(TICKERS_FILE)["Ticker"]
            .dropna()
            .str.strip()
            .str.upper()
            .tolist()
        )
        logger.info("Đọc được %d mã từ %s", len(tickers), TICKERS_FILE)
        return tickers
    except FileNotFoundError:
        logger.error("Không tìm thấy %s — tạo file và thêm mã vào.", TICKERS_FILE)
        return []


def fetch_history(symbol: str, start: str, end: str, source: str = "KBS", max_retries: int = 3) -> pd.DataFrame | None:
    """
    Tải lịch sử OHLCV cho 1 mã từ nguồn KBS (index=date).
    Ưu tiên gọi trực tiếp Quote adapter để tránh bị tính lặp 2 lần request vào quota UI của vnai.
    Tích hợp SafeRateLimiter tự động điều tiết theo tier, đảm bảo không chạm trần per-minute.
    Trả về None nếu không tải được — KHÔNG raise exception.

    Volume = NaN nếu nguồn không cung cấp (vd. KBS cho index có thể thiếu);
    caller phải xử lý NaN volume (vd. fill 0 hoặc skip).
    """
    sym = str(symbol).strip().upper()

    for attempt in range(1, max_retries + 1):
        rate_limiter.wait_if_needed()
        df = None
        rate_limited = False

        # Thử 1: Gọi trực tiếp Quote adapter (chuẩn xác, tránh nhân đôi counter UI)
        try:
            from vnstock import Quote
            df = Quote(symbol=sym, source=source).history(
                start=start, end=end, interval="1D"
            )
        except Exception as err:
            if _is_rate_limit_error(err):
                rate_limited = True
                wait_sec = _extract_retry_after(err)
                rate_limiter.handle_rate_limit_exceeded(wait_sec)
                logger.info("  %s bị rate limit (lần %d/%d), đang thử lại...", sym, attempt, max_retries)
                continue
            logger.debug("%s Quote adapter thử thất bại: %s — fallback sang Market UI", sym, err)

        # Thử 2: Nếu Quote không trả về và không bị rate limit, fallback sang Market UI
        if (df is None or df.empty) and not rate_limited:
            try:
                rate_limiter.wait_if_needed()
                from vnstock import Market
                mkt = Market()
                if sym in ("VNINDEX", "VN30", "HNX", "UPCOM"):
                    df = mkt.index(sym).ohlcv(start=start, end=end, interval="1D", source=source)
                else:
                    df = mkt.equity(sym).ohlcv(start=start, end=end, interval="1D", source=source)
            except Exception as e:
                if _is_rate_limit_error(e):
                    wait_sec = _extract_retry_after(e)
                    rate_limiter.handle_rate_limit_exceeded(wait_sec)
                    logger.info("  %s Market bị rate limit (lần %d/%d), đang thử lại...", sym, attempt, max_retries)
                    continue
                logger.debug("  %s Market thất bại: %s", sym, e)

        if df is not None and not df.empty:
            try:
                # Chuẩn hóa tên cột chữ thường
                df.columns = [str(c).lower() for c in df.columns]

                keep_cols = ["time", "close"]
                if "volume" in df.columns:
                    keep_cols.append("volume")

                out = df[keep_cols].set_index("time")
                out.index = pd.to_datetime(out.index).normalize().tz_localize(None)
                out = out[~out.index.duplicated(keep="last")]

                if "volume" not in out.columns:
                    out["volume"] = np.nan
                    logger.info("✓ %-8s [%s] — %d ngày (volume thiếu, fill NaN)", sym, source, len(out))
                else:
                    logger.info("✓ %-8s [%s] — %d ngày (close+vol)", sym, source, len(out))
                return out[["close", "volume"]]
            except Exception as parse_err:
                logger.warning("✗ %-8s [%s] — Lỗi chuẩn hóa dữ liệu: %s", sym, source, parse_err)
                return None

        # Nếu không có dữ liệu và không phải do rate limit thì không cần retry mã này
        if not rate_limited:
            break

    logger.warning("✗ %-8s [%s] — Không lấy được dữ liệu sau %d lần thử.", sym, source, max_retries)
    return None


# Backwards-compat: code cũ vẫn import fetch_close
def fetch_close(symbol: str, start: str, end: str, source: str = "KBS") -> pd.Series | None:
    """Wrapper giữ tương thích — trả về Series close only từ KBS."""
    df = fetch_history(symbol, start, end, source)
    if df is None:
        return None
    return df["close"].rename(symbol)


def _load_existing_market_data(path: Path) -> pd.DataFrame | None:
    """Đọc file market_data.csv hiện có, trả về DataFrame hoặc None."""
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        logger.info("Đã đọc file hiện có: %d ngày × %d mã, last_date=%s",
                    df.shape[0], df.shape[1], df.index.max().strftime('%Y-%m-%d'))
        return df
    except Exception as e:
        logger.warning("Không đọc được file cũ %s: %s — sẽ tạo mới.", path, e)
        return None


def _merge_and_save(df_new: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Merge data mới vào file cũ (nếu có). df_new ưu tiên, NaN không ghi đè data cũ."""
    df_old = _load_existing_market_data(path)
    if df_old is not None:
        # df_new.combine_first(df_old): union index, ưu tiên df_new (nếu non-NaN), fallback df_old
        df_merged = df_new.combine_first(df_old).sort_index()
    else:
        df_merged = df_new.sort_index()

    DATA_LAKE.mkdir(parents=True, exist_ok=True)
    df_merged.to_csv(path)
    logger.info("Đã lưu: %d ngày × %d mã → %s", df_merged.shape[0], df_merged.shape[1], path)
    return df_merged


def _fetch_index(symbol: str, start: str, end: str) -> pd.DataFrame | None:
    """Fetch index (VNINDEX/VN30) từ nguồn KBS duy nhất. Trả về DF [close, volume]."""
    return fetch_history(symbol, start, end, source="KBS")


# Alias giữ tương thích
_fetch_index_with_fallback = _fetch_index


def update_vnindex(start: str, end: str) -> bool:
    """Tải VNINDEX (close + volume) vào data_lake/vnindex_cache.csv.

    Cột: VNINDEX, VNINDEX_volume.
    close ffill (để skip ngày nghỉ); volume KHÔNG ffill (NaN giữ nguyên =
    ngày không giao dịch → 0 sẽ làm méo Amihud).
    """
    logger.info("Đang tải VNINDEX...")
    df = _fetch_index_with_fallback("VNINDEX", start, end)
    if df is None:
        logger.warning("Không tải được VNINDEX, bỏ qua lưu file VNINDEX.")
        return False

    df_new = df.rename(columns={"close": "VNINDEX", "volume": "VNINDEX_volume"}).sort_index()
    df_new["VNINDEX"] = df_new["VNINDEX"].ffill()
    _merge_and_save(df_new, VNINDEX_DATA)
    return True


def update_vn30(start: str, end: str) -> bool:
    """Tải VN30 index (close + volume) vào data_lake/vn30_cache.csv.

    Cột: VN30, VN30_volume. Volume cần thiết cho ESR Monitor S_PRES.
    """
    logger.info("Đang tải VN30...")
    df = _fetch_index_with_fallback("VN30", start, end)
    if df is None:
        logger.warning("Không tải được VN30, bỏ qua lưu file VN30.")
        return False

    df_new = df.rename(columns={"close": "VN30", "volume": "VN30_volume"}).sort_index()
    df_new["VN30"] = df_new["VN30"].ffill()
    _merge_and_save(df_new, VN30_DATA)
    return True


def update(backfill_days: int | None = None, from_date: str | None = None):
    logger.info("Dùng DATA_LAKE: %s", DATA_LAKE)
    logger.info("Dùng MARKET_DATA: %s", MARKET_DATA)
    logger.info("Dùng TICKERS_FILE: %s", TICKERS_FILE)
    if "/command/data_lake" in str(DATA_LAKE).replace("\\", "/"):
        raise RuntimeError(f"Sai output path: {DATA_LAKE} (phải là root data_lake)")

    tickers = load_tickers()
    if not tickers:
        logger.error("tickers.csv trống. Thêm mã vào rồi chạy lại.")
        return

    # Xác định khoảng thờ gian cần tải
    df_existing = _load_existing_market_data(MARKET_DATA)
    today_str = datetime.now().strftime("%Y-%m-%d")

    if from_date:
        start = from_date
        logger.info("Mode: BACKFILL from %s", start)
    elif backfill_days:
        start = (datetime.now() - timedelta(days=backfill_days)).strftime("%Y-%m-%d")
        logger.info("Mode: BACKFILL %d days → %s", backfill_days, start)
    elif df_existing is not None:
        # Incremental: tải từ ngày cuối file đến hôm nay
        last_date = df_existing.index.max()
        # Lùi 3 ngày để catch-up nếu có gap
        start_date = last_date - timedelta(days=3)
        start = start_date.strftime("%Y-%m-%d")
        logger.info("Mode: INCREMENTAL from %s (last_date=%s)", start, last_date.strftime('%Y-%m-%d'))
    else:
        start = (datetime.now() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        logger.info("Mode: FULL (file chưa tồn tại) from %s", start)

    end = datetime.now().strftime("%Y-%m-%d")
    logger.info("Khoảng thờ gian: %s → %s", start, end)

    update_vnindex(start, end)
    update_vn30(start, end)

    # Dữ liệu cổ phiếu — loại VNINDEX và VN30 khỏi market_data (lưu riêng)
    stock_tickers = [t for t in tickers if t not in ("VNINDEX", "VN30")]
    
    # Đảm bảo VN30F1M luôn được tải cho công cụ Manipulation Detection
    if "VN30F1M" not in stock_tickers:
        stock_tickers.append("VN30F1M")
        logger.info("Đã tự động thêm VN30F1M vào danh sách cập nhật.")

    if not stock_tickers:
        logger.error("Không có ticker cổ phiếu hợp lệ sau khi loại VNINDEX.")
        return

    close_list = []
    volume_list = []
    failed = []

    # Tính start date mặc định (lookback) cho các mã mới nếu đang ở chế độ incremental
    full_lookback_start = (datetime.now() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    for i, symbol in enumerate(stock_tickers, 1):
        # Xác định start date cho riêng mã này
        if df_existing is not None and symbol in df_existing.columns:
            last_valid = df_existing[symbol].dropna().index.max()
            if pd.notna(last_valid):
                # Use the symbol's own last valid date, not only the global file
                # last_date. This backfills tail gaps such as stale VN30F1M while
                # other columns already extend to newer sessions.
                symbol_start = (last_valid - timedelta(days=3)).strftime("%Y-%m-%d")
                logger.info(
                    "[%d/%d] Đang tải %s (incremental từ %s, last_valid=%s)...",
                    i,
                    len(stock_tickers),
                    symbol,
                    symbol_start,
                    last_valid.strftime("%Y-%m-%d"),
                )
            else:
                symbol_start = full_lookback_start
                logger.info(
                    "[%d/%d] Đang tải %s (cột cũ nhưng toàn NaN, tải đầy đủ từ %s)...",
                    i,
                    len(stock_tickers),
                    symbol,
                    symbol_start,
                )
        else:
            symbol_start = full_lookback_start
            logger.info("[%d/%d] Đang tải %s (mã mới, tải đầy đủ từ %s)...", i, len(stock_tickers), symbol, symbol_start)

        df_hist = fetch_history(symbol, symbol_start, end, source="KBS")
        if df_hist is not None:
            close_list.append(df_hist["close"].rename(symbol))
            volume_list.append(df_hist["volume"].rename(symbol))
        else:
            failed.append(symbol)

    logger.info("─" * 50)
    logger.info("Thành công: %d / %d mã", len(close_list), len(stock_tickers))

    if failed:
        logger.warning("Bỏ qua %d mã: %s", len(failed), ", ".join(failed))

    if len(close_list) < 2:
        if df_existing is not None and not df_existing.empty:
            logger.info("Dữ liệu hiện tại đã đầy đủ hoặc không có phiên giao dịch mới cần cập nhật.")
            return
        logger.error("Chưa đủ dữ liệu (< 2 mã) — không lưu file.")
        return

    # close: ffill để skip cuối tuần / lễ
    df_close = pd.concat(close_list, axis=1).sort_index().ffill()
    _merge_and_save(df_close, MARKET_DATA)

    # volume: KHÔNG ffill (volume = 0 hoặc NaN giữ ý nghĩa "không giao dịch")
    df_volume = pd.concat(volume_list, axis=1).sort_index()
    # Sanitize: thay <0 / inf bằng NaN; cho phép 0 thật
    df_volume = df_volume.replace([np.inf, -np.inf], np.nan)
    df_volume = df_volume.mask(df_volume < 0, np.nan)
    _merge_and_save(df_volume, MARKET_VOLUME)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cập nhật dữ liệu giá từ VNStock")
    parser.add_argument("--backfill", type=int, metavar="DAYS",
                        help="Backfill N ngày lịch sử (ví dụ: 2190 ~ 6 năm)")
    parser.add_argument("--from-date", type=str, metavar="YYYY-MM-DD",
                        help="Backfill từ ngày cụ thể")
    args = parser.parse_args()

    update(backfill_days=args.backfill, from_date=args.from_date)
