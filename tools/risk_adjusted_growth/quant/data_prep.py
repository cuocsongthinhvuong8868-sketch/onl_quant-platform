import hashlib
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from config import DATA_LAKE

logger = logging.getLogger(__name__)

# market_data.csv lưu giá theo nghìn VND (convention vnstock cho VN stocks):
# VCB = 61.5 ↔ 61,500 VND. BVPS từ statistics JSON ở đơn vị VND đầy đủ.
# Để P/B đồng nhất đơn vị: price * 1000 / bvps.
PRICE_THOUSANDS_TO_VND = 1000

# Cap cash payout 50% để tránh outlier (special dividend) làm méo ROE retention.
# Có thể nâng nếu khẩu vị ngân hàng có chính sách chia cao bền vững.
CASH_PAYOUT_CAP = 0.5

RAG_DATA_DIR = DATA_LAKE / "risk_adjusted_growth"
STATISTICS_JSON_DIR = RAG_DATA_DIR / "statistics_json"
FINANCIAL_REPORT_JSON_DIR = RAG_DATA_DIR / "financial_report_json"
RAG_BANK_UNIVERSE = (
    "VCB", "BID", "CTG", "TCB", "VPB", "MBB", "ACB", "SSB",
    "SHB", "HDB", "VIB", "LPB", "EIB", "OCB", "MSB", "TPB",
)
STATISTICS_ROWS_REQUIRED = ("ROE (%)", "PB", "Market Cap", "Outstanding Shares")
STATISTICS_ROWS_OPTIONAL = ("Dividend Yield (%)", "ROA (%)")
STATISTICS_ROWS_TO_KEEP = STATISTICS_ROWS_REQUIRED + STATISTICS_ROWS_OPTIONAL
FINANCIAL_REPORT_ROWS_TO_KEEP = {
    "Income Statement": ("Net profit/(loss) after tax",),
    "Cash Flow": ("Dividends paid",),
}
ROE_LOOKBACK_QUARTERS = 20
PAYOUT_LOOKBACK_QUARTERS = 20


def _parse_number(value) -> float:
    if value is None:
        return np.nan
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "—", "N/A", "NA", "nan", "None"}:
        return np.nan
    sign = -1.0 if text.startswith("(") and text.endswith(")") else 1.0
    text = text.strip("()").replace("%", "").strip()
    multiplier = 1.0
    suffix = text[-1:].upper()
    if suffix in {"K", "M", "B", "T"}:
        multiplier = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[suffix]
        text = text[:-1]
    try:
        return sign * float(text) * multiplier
    except ValueError:
        return np.nan


def _financial_statistics_rows(payload: dict) -> list[list]:
    return (
        payload.get("financialData", {})
        .get("Financial Statistics", {})
        .get("tableRows", [])
    )


def _row_series(payload: dict, row_label: str) -> pd.Series:
    rows = _financial_statistics_rows(payload)
    if len(rows) < 2:
        return pd.Series(dtype=float)
    periods = [str(x).strip() for x in rows[0]]
    for row in rows[1:]:
        if not row or str(row[0]).strip() != row_label:
            continue
        values = row[1 : len(periods) + 1]
        s = pd.Series(values, index=periods[: len(values)])
        return s.map(_parse_number).dropna()
    return pd.Series(dtype=float)


def _section_rows(payload: dict, section_name: str) -> list[list]:
    return (
        payload.get("financialData", {})
        .get(section_name, {})
        .get("tableRows", [])
    )


def _section_row_series(payload: dict, section_name: str, row_label: str) -> pd.Series:
    rows = _section_rows(payload, section_name)
    if len(rows) < 2:
        return pd.Series(dtype=float)
    periods = [str(x).strip() for x in rows[0][1:]]
    for row in rows[1:]:
        if not row or str(row[0]).strip() != row_label:
            continue
        values = row[1 : len(periods) + 1]
        s = pd.Series(values, index=periods[: len(values)])
        return s.map(_parse_number).dropna()
    return pd.Series(dtype=float)


def _latest_value(series: pd.Series) -> float:
    if series is None or series.empty:
        return np.nan
    return float(series.dropna().iloc[-1])


def _profile_from_payload(payload: dict, ticker: str) -> dict:
    profile = payload.get("profile")
    if isinstance(profile, dict):
        return profile

    raw_recent = (
        payload.get("loginStatus", {})
        .get("lsData", {})
        .get("recent-companies")
    )
    if not raw_recent:
        return {}
    try:
        companies = json.loads(raw_recent)
    except Exception:
        return {}
    ticker = ticker.upper()
    for company in companies:
        if str(company.get("symbol", "")).upper() == ticker:
            return company
    return {}


def _cash_payout_from_financial_report(payload: dict) -> dict:
    net_profit = _section_row_series(payload, "Income Statement", "Net profit/(loss) after tax")
    dividends_paid = _section_row_series(payload, "Cash Flow", "Dividends paid")
    common_periods = net_profit.dropna().index.intersection(dividends_paid.dropna().index)
    if len(common_periods) == 0:
        return {
            "ratio": 0.0,
            "cash_dividends_paid_20q": 0.0,
            "net_profit_20q": np.nan,
            "periods": "",
            "source": "missing cash-flow payout rows",
        }

    lookback_periods = list(common_periods[-PAYOUT_LOOKBACK_QUARTERS:])
    net_profit_20q = float(net_profit.loc[lookback_periods].sum())
    cash_dividends_paid_20q = float((-dividends_paid.loc[lookback_periods].clip(upper=0)).sum())
    if pd.isna(net_profit_20q) or net_profit_20q <= 0 or cash_dividends_paid_20q <= 0:
        ratio = 0.0
    else:
        ratio = min(cash_dividends_paid_20q / net_profit_20q, CASH_PAYOUT_CAP)

    return {
        "ratio": float(ratio),
        "cash_dividends_paid_20q": cash_dividends_paid_20q,
        "net_profit_20q": net_profit_20q,
        "periods": f"{lookback_periods[0]}-{lookback_periods[-1]}",
        "source": "cash_flow_dividends_paid_20q/net_profit_after_tax_20q",
    }


def _implied_bvps_from_statistics(market_cap: pd.Series, shares: pd.Series, pb: pd.Series) -> float:
    market_cap_latest = _latest_value(market_cap)
    shares_latest = _latest_value(shares)
    pb_latest = _latest_value(pb)
    if (
        pd.isna(market_cap_latest)
        or pd.isna(shares_latest)
        or pd.isna(pb_latest)
        or market_cap_latest <= 0
        or shares_latest <= 0
        or pb_latest <= 0
    ):
        return np.nan
    implied_price_vnd = market_cap_latest / shares_latest
    return float(implied_price_vnd / pb_latest)


def _daily_price_thousand_vnd(ticker: str, price_row) -> float:
    if price_row is None:
        return np.nan
    if isinstance(price_row, pd.Series):
        value = price_row.get(ticker, np.nan)
    elif isinstance(price_row, dict):
        value = price_row.get(ticker, np.nan)
    else:
        value = np.nan
    return float(value) if pd.notna(value) else np.nan


def _roe_geomean(roe: pd.Series) -> float:
    if roe.empty:
        return np.nan
    roe = roe.tail(ROE_LOOKBACK_QUARTERS)
    positive = roe[roe > 0]
    if positive.empty:
        return float(roe.mean())
    return float(np.exp(np.log1p(positive).mean()) - 1.0)


def _normalize_roe_percent(series: pd.Series) -> pd.Series:
    roe = pd.to_numeric(series, errors="coerce").dropna()
    if roe.empty:
        return roe
    if roe.abs().median() > 1:
        roe = roe / 100.0
    return roe


def _sanitize_statistics_payload(payload: dict) -> dict:
    ticker = str(payload.get("ticker") or "").upper()
    rows = _financial_statistics_rows(payload)
    kept_rows = []
    if rows:
        kept_rows.append(rows[0])
        for row in rows[1:]:
            if row and str(row[0]).strip() in STATISTICS_ROWS_TO_KEEP:
                kept_rows.append(row)

    profile = _profile_from_payload(payload, ticker)
    sector = profile.get("sector") if isinstance(profile.get("sector"), dict) else {}
    return {
        "ticker": ticker,
        "url": payload.get("url", ""),
        "timestamp": payload.get("timestamp", ""),
        "profile": {
            "symbol": profile.get("symbol", ticker),
            "exchange_id": profile.get("exchange_id", ""),
            "sector_name": profile.get("sector_name") or sector.get("name", ""),
            "sector_local_name": profile.get("sector_local_name") or sector.get("local_name", ""),
        },
        "financialData": {
            "Financial Statistics": {
                "tab": "Financial Statistics",
                "tableRows": kept_rows,
            }
        },
    }


def _sanitize_financial_report_payload(payload: dict) -> dict:
    ticker = str(payload.get("ticker") or "").upper()
    financial_data = {}
    for section_name, labels in FINANCIAL_REPORT_ROWS_TO_KEEP.items():
        rows = _section_rows(payload, section_name)
        kept_rows = []
        if rows:
            kept_rows.append(rows[0])
            label_set = set(labels)
            for row in rows[1:]:
                if row and str(row[0]).strip() in label_set:
                    kept_rows.append(row)
        financial_data[section_name] = {
            "tab": section_name,
            "tableRows": kept_rows,
        }

    return {
        "ticker": ticker,
        "url": payload.get("url", ""),
        "timestamp": payload.get("timestamp", ""),
        "financialData": financial_data,
    }


def copy_statistics_json_feed(
    source_dir: str | Path,
    dest_dir: str | Path = STATISTICS_JSON_DIR,
    sanitize: bool = True,
    universe: tuple[str, ...] | set[str] | None = RAG_BANK_UNIVERSE,
) -> int:
    """
    Copy MozyFin Statistics JSON into the project data lake.

    Sanitized copies keep only the rows used by this tool and a minimal profile,
    avoiding browser/local-storage metadata from the raw scrape.
    """
    source = Path(source_dir)
    dest = Path(dest_dir)
    if not source.exists():
        raise FileNotFoundError(source)
    dest.mkdir(parents=True, exist_ok=True)
    for old_file in dest.glob("*_financial_statistics.json"):
        old_file.unlink()

    universe_set = {str(t).upper() for t in universe} if universe else None
    count = 0
    for path in sorted(source.glob("*_financial_statistics.json")):
        ticker = path.name.split("_", 1)[0].upper()
        if universe_set and ticker not in universe_set:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        out_payload = _sanitize_statistics_payload(payload) if sanitize else payload
        out_path = dest / path.name
        out_path.write_text(
            json.dumps(out_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        count += 1
    return count


def copy_financial_report_json_feed(
    source_dir: str | Path,
    dest_dir: str | Path = FINANCIAL_REPORT_JSON_DIR,
    sanitize: bool = True,
    universe: tuple[str, ...] | set[str] | None = RAG_BANK_UNIVERSE,
) -> int:
    """
    Copy MozyFin BCTC JSON into the RAG data lake.

    Sanitized copies keep only net profit after tax and dividends paid, which
    are the rows required to compute cash payout from actual cash flow.
    """
    source = Path(source_dir)
    dest = Path(dest_dir)
    if not source.exists():
        raise FileNotFoundError(source)
    dest.mkdir(parents=True, exist_ok=True)
    for old_file in dest.glob("*_financial_report.json"):
        old_file.unlink()

    universe_set = {str(t).upper() for t in universe} if universe else None
    count = 0
    for path in sorted(source.glob("*_financial_report.json")):
        ticker = path.name.split("_", 1)[0].upper()
        if universe_set and ticker not in universe_set:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        out_payload = _sanitize_financial_report_payload(payload) if sanitize else payload
        out_path = dest / path.name
        out_path.write_text(
            json.dumps(out_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        count += 1
    return count


def risk_adjusted_growth_source_signature(
    statistics_dir: str | Path = STATISTICS_JSON_DIR,
    financial_report_dir: str | Path = FINANCIAL_REPORT_JSON_DIR,
) -> str:
    files = []
    for directory, pattern in (
        (Path(statistics_dir), "*_financial_statistics.json"),
        (Path(financial_report_dir), "*_financial_report.json"),
    ):
        files.extend(sorted(directory.glob(pattern)))
    if not files:
        return "NO_RAG_JSON"

    digest = hashlib.sha1()
    latest_timestamp = ""
    for file_path in sorted(files):
        raw = file_path.read_bytes()
        digest.update(file_path.parent.name.encode("utf-8"))
        digest.update(file_path.name.encode("utf-8"))
        digest.update(raw)
        try:
            payload = json.loads(raw.decode("utf-8"))
            latest_timestamp = max(latest_timestamp, str(payload.get("timestamp", "")))
        except Exception:
            pass

    if latest_timestamp:
        label = pd.to_datetime(latest_timestamp, errors="coerce")
        date_label = latest_timestamp[:10] if pd.isna(label) else label.strftime("%Y-%m-%d")
    else:
        latest_mtime = max(file_path.stat().st_mtime for file_path in files)
        date_label = pd.to_datetime(latest_mtime, unit="s").strftime("%Y-%m-%d")
    return f"{date_label}:{digest.hexdigest()[:12]}"


def load_statistics_ratio_table(
    statistics_dir: str | Path = STATISTICS_JSON_DIR,
    financial_report_dir: str | Path = FINANCIAL_REPORT_JSON_DIR,
    universe: tuple[str, ...] | set[str] | None = RAG_BANK_UNIVERSE,
) -> pd.DataFrame:
    path = Path(statistics_dir)
    files = sorted(path.glob("*_financial_statistics.json"))
    if not files:
        raise FileNotFoundError(
            f"Không tìm thấy JSON statistics trong {path}. "
            "Hãy copy feed vào data_lake/risk_adjusted_growth/statistics_json."
        )
    report_path = Path(financial_report_dir)
    if not report_path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy BCTC JSON trong {report_path}. "
            "Hãy copy feed vào data_lake/risk_adjusted_growth/financial_report_json."
        )

    rows = []
    skipped = []
    universe_set = {str(t).upper() for t in universe} if universe else None
    for file_path in files:
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            skipped.append(f"{file_path.name}: JSON lỗi ({exc})")
            continue

        ticker = str(payload.get("ticker") or file_path.name.split("_")[0]).upper()
        if universe_set and ticker not in universe_set:
            continue
        report_file = report_path / f"{ticker}_financial_report.json"
        if not report_file.exists():
            skipped.append(f"{ticker}: thiếu BCTC financial_report JSON")
            continue
        try:
            report_payload = json.loads(report_file.read_text(encoding="utf-8"))
        except Exception as exc:
            skipped.append(f"{ticker}: BCTC JSON lỗi ({exc})")
            continue

        roe = _normalize_roe_percent(_row_series(payload, "ROE (%)"))
        pb = _row_series(payload, "PB")
        market_cap = _row_series(payload, "Market Cap")
        shares = _row_series(payload, "Outstanding Shares")
        bvps = _implied_bvps_from_statistics(market_cap, shares, pb)
        if roe.empty or pb.empty or pd.isna(bvps):
            skipped.append(f"{ticker}: thiếu ROE/PB/MarketCap/Shares")
            continue

        profile = _profile_from_payload(payload, ticker)
        payout = _cash_payout_from_financial_report(report_payload)
        pb_latest = _latest_value(pb)
        roe_recent = roe.tail(ROE_LOOKBACK_QUARTERS)
        rows.append(
            {
                "Ticker": ticker,
                "Ngân hàng": ticker,
                "Geomean ROE": _roe_geomean(roe),
                "Stdev ROE": float(roe_recent.std()) if len(roe_recent) > 1 else 0.0,
                "Cash Payout Ratio": payout["ratio"],
                "Cash Dividends Paid 20Q": payout["cash_dividends_paid_20q"],
                "Net Profit 20Q": payout["net_profit_20q"],
                "Cash Payout Periods": payout["periods"],
                "Cash Payout Source": payout["source"],
                "BVPS": bvps,
                "P/B Statistics": pb_latest,
                "Latest Period": str(pb.dropna().index[-1]),
                "ROE Lookback Quarters": int(len(roe_recent)),
                "Source Timestamp": str(payload.get("timestamp", "")),
                "Sector": (
                    profile.get("sector_name")
                    or (profile.get("sector", {}) or {}).get("name", "")
                ),
                "Exchange": profile.get("exchange_id", ""),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("Không build được statistics ratio table; " + "; ".join(skipped[:5]))

    df = df.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["Geomean ROE", "Stdev ROE", "BVPS", "P/B Statistics"]
    )
    df = df[(df["BVPS"] > 0) & (df["P/B Statistics"] > 0) & (df["Geomean ROE"].notna())].copy()
    if df.empty:
        raise ValueError("Statistics ratio table rỗng sau khi lọc ROE/PB hợp lệ.")
    return df.sort_values("Ticker").reset_index(drop=True)


def build_base_table_from_statistics(
    statistics_dir: str | Path = STATISTICS_JSON_DIR,
    financial_report_dir: str | Path = FINANCIAL_REPORT_JSON_DIR,
    price_row=None,
    universe: tuple[str, ...] | set[str] | None = RAG_BANK_UNIVERSE,
) -> pd.DataFrame:
    if price_row is None:
        raise ValueError("Risk-Adjusted Growth cần daily price row để tính P/B daily = close / BVPS.")

    ratios = load_statistics_ratio_table(
        statistics_dir,
        financial_report_dir=financial_report_dir,
        universe=universe,
    )
    rows = []
    missing_price = []
    for _, row in ratios.iterrows():
        ticker = str(row["Ticker"]).upper()
        price_thousand = _daily_price_thousand_vnd(ticker, price_row)
        if pd.isna(price_thousand) or price_thousand <= 0:
            missing_price.append(ticker)
            continue

        out = row.to_dict()
        out["Daily Close"] = price_thousand
        out["P/B Gốc"] = (price_thousand * PRICE_THOUSANDS_TO_VND) / float(row["BVPS"])
        rows.append(out)

    if not rows:
        raise ValueError(
            "Không có ticker nào có daily close hợp lệ trong market_data.csv để tính P/B daily."
        )
    if missing_price:
        logger.warning("Bỏ qua ticker thiếu daily close cho RAG: %s", ", ".join(missing_price))
    return pd.DataFrame(rows).reset_index(drop=True)
