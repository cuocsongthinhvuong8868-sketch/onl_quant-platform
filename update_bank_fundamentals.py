"""
Cập nhật dữ liệu fundamentals cho tool Risk-Adjusted Growth.
Lưu output vào data_lake để app chỉ đọc file, không gọi API trong UI.
"""
import os
import time
import logging
import pandas as pd
from scipy.stats import gmean

from config import VNSTOCK_API_KEY, DATA_LAKE

os.environ["VNSTOCK_API_KEY"] = VNSTOCK_API_KEY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

HOSE_BANKS = [
    "VCB", "BID", "CTG", "TCB", "VPB", "MBB", "ACB", "SSB",
    "SHB", "HDB", "VIB", "LPB", "EIB", "OCB", "MSB", "TPB",
]


def extract_ratio_series(df: pd.DataFrame, item_keyword: str) -> pd.Series:
    row = df[df["item"].str.contains(item_keyword, case=False, na=False)]
    if row.empty:
        return pd.Series(dtype=float)

    r_dict = row.iloc[0].to_dict()
    r_dict.pop("item", None)
    r_dict.pop("item_id", None)

    quarters = [k for k in r_dict.keys() if str(k).startswith("20")]
    quarters.sort(reverse=True)

    dedup = {}
    for q in quarters:
        clean_q = str(q).split("_")[0]
        if clean_q not in dedup:
            dedup[clean_q] = r_dict[q]

    s = pd.Series(dedup)
    return pd.to_numeric(s, errors="coerce").dropna()


def fetch_bank_fundamentals() -> pd.DataFrame:
    from vnstock import Finance

    rows = []
    for bank in HOSE_BANKS:
        logger.info("Đang xử lý %s", bank)
        try:
            fin = Finance(symbol=bank, source="KBS")
            df_ratio = fin.ratio(period="quarter")
            if df_ratio is None or df_ratio.empty:
                logger.warning("%s: ratio rỗng, bỏ qua", bank)
                continue

            roe = extract_ratio_series(df_ratio, "ROE bình quân 4 quý gần nhất")
            if roe.empty:
                roe = extract_ratio_series(df_ratio, "ROE")
            bvps = extract_ratio_series(df_ratio, "BVPS|Giá trị sổ sách")

            if roe.empty or bvps.empty:
                logger.warning("%s: thiếu ROE/BVPS", bank)
                continue

            if roe.mean() > 1:
                roe = roe / 100.0
            roe = roe.head(20)

            roe_stdev = float(roe.std())
            roe_positive = roe[roe > 0]
            roe_geomean = float(gmean(1 + roe_positive) - 1) if not roe_positive.empty else float(roe.mean())

            rows.append(
                {
                    "ticker": bank,
                    "Geomean ROE": roe_geomean,
                    "Stdev ROE": roe_stdev,
                    "BVPS": float(bvps.iloc[0]),
                }
            )
        except Exception as e:
            logger.warning("%s: %s", bank, e)

        time.sleep(1.1)

    return pd.DataFrame(rows)


def main():
    DATA_LAKE.mkdir(parents=True, exist_ok=True)
    df = fetch_bank_fundamentals()
    if df.empty:
        logger.error("Không thu được dữ liệu fundamentals.")
        return

    out = DATA_LAKE / "bank_fundamentals.csv"
    df.to_csv(out, index=False)
    logger.info("Đã lưu fundamentals: %s", out)


if __name__ == "__main__":
    main()
