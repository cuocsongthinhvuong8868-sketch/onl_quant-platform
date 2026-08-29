import os
import json
import logging
import pandas as pd
import glob
from pathlib import Path

from tools.bank_valuation.quant.engine.utils import parse_number


logger = logging.getLogger(__name__)


FINANCIAL_STATISTIC_FIELDS = {
    "number_of_shares_market_cap": "shares_outstanding",
    "market_cap": "market_cap",
    "pb": "pb",
    "roe": "roe",
    "roa": "roa",
    "ldr_loan_deposit_ratio": "ldr",
    "npl": "npl_ratio",
    "loans_loss_reserves_to_npls": "provision_coverage",
    "provision_to_outstanding_loans": "credit_cost",
    "car": "car",
    "casa_ratio": "casa_ratio",
}


def _canonical_metric_name(value) -> str:
    """Remove the live UI trend suffix appended to statement row labels."""
    if value is None:
        return ""
    # New MozyFin captures append values such as ``\n▲ 4.2%`` to every
    # statement label.  The first line remains the stable account name.
    return str(value).splitlines()[0].strip()


class DataLoader:
    def __init__(self, data_folder: str):
        self.data_folder = data_folder

    def load_all(self):
        """Load all supported files from the data folder."""
        data_frames = []
        
        # Search recursively for json, xlsx, xls, csv
        search_path = os.path.join(self.data_folder, "**", "*")
        for file_path in glob.glob(search_path, recursive=True):
            ext = Path(file_path).suffix.lower()
            if ext == '.json':
                df = self._load_json(file_path)
                if df is not None and not df.empty:
                    data_frames.append(df)
            elif ext in ['.xlsx', '.xls']:
                df = self._load_excel(file_path)
                if df is not None and not df.empty:
                    data_frames.append(df)
            elif ext == '.csv':
                df = self._load_csv(file_path)
                if df is not None and not df.empty:
                    data_frames.append(df)
                
        if not data_frames:
            return pd.DataFrame()
            
        final_df = pd.concat(data_frames, ignore_index=True).copy()
        final_df = final_df.groupby(["ticker", "period"], as_index=False).first()
        return final_df

    def _load_json(self, file_path: str) -> pd.DataFrame:
        """Load the specific JSON structure provided."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            ticker = data.get("ticker")
            if not ticker:
                return None

            api_statistics = self._load_financial_statistics_api(data, ticker)
            if not api_statistics.empty:
                return api_statistics

            fin_data = data.get("financialData", {})
            if not fin_data:
                dom_snapshot = data.get("financialStatistics", {}).get("domSnapshot", {})
                if dom_snapshot.get("tableRows"):
                    fin_data = {"Financial Statistics": dom_snapshot}

            all_records = {}
            
            for tab_name, tab_data in fin_data.items():
                table_rows = tab_data.get("tableRows", [])
                if not table_rows or len(table_rows) < 2:
                    continue
                    
                periods = table_rows[0]
                
                parsed_data = {}
                max_values_len = 0
                for row in table_rows[1:]:
                    if not row or len(row) == 0:
                        continue
                    metric_name = _canonical_metric_name(row[0])
                    if not metric_name:
                        continue
                    values = row[1:]
                    parsed_data[metric_name] = values
                    if len(values) > max_values_len:
                        max_values_len = len(values)
                        
                offset = max(0, len(periods) - max_values_len)
                
                for i, period in enumerate(periods):
                    if i < offset:
                        continue
                    if period not in all_records:
                        all_records[period] = {"ticker": ticker, "period": period}
                        
                    for metric_name, values in parsed_data.items():
                        val_idx = i - offset
                        if val_idx >= 0 and val_idx < len(values):
                            all_records[period][metric_name] = parse_number(values[val_idx])
                        else:
                            if metric_name not in all_records[period]:
                                all_records[period][metric_name] = float('nan')
                                
            if not all_records:
                return None
                
            return pd.DataFrame(list(all_records.values()))
            
        except Exception:
            logger.exception("Error loading JSON file: %s", file_path)
            return None

    def _load_financial_statistics_api(self, data: dict, ticker: str) -> pd.DataFrame:
        """Read the structured statistics embedded in MozyFin v2 captures."""
        responses = data.get("financialStatistics", {}).get("apiResponses", [])
        records = []
        for response in responses:
            if "/financial-statistic" not in str(response.get("url", "")):
                continue
            parsed_body = response.get("parsedBody")
            if not isinstance(parsed_body, dict):
                continue
            rows = parsed_body.get("data", [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    quarter = int(row.get("quarter"))
                    year = int(row.get("year"))
                except (TypeError, ValueError):
                    continue
                if quarter not in range(1, 5):
                    continue

                record = {"ticker": ticker, "period": f"Q{quarter} {year}"}
                for source_name, target_name in FINANCIAL_STATISTIC_FIELDS.items():
                    if source_name in row:
                        record[target_name] = parse_number(row[source_name])
                records.append(record)

        return pd.DataFrame(records)

    def _infer_ticker(self, file_path: str) -> str:
        return Path(file_path).stem.split("_")[0].upper()

    def _normalize_tabular_columns(self, df: pd.DataFrame, file_path: str) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()

        df = df.dropna(how="all").dropna(axis=1, how="all")
        if df.empty:
            return pd.DataFrame()

        lower_cols = {str(col).strip().lower(): col for col in df.columns}
        ticker_col = lower_cols.get("ticker")
        period_col = lower_cols.get("period")

        if period_col is not None:
            records = df.copy()
            if ticker_col is None:
                records["ticker"] = self._infer_ticker(file_path)
            skip_cols = {period_col}
            if ticker_col is not None:
                skip_cols.add(ticker_col)
            else:
                skip_cols.add("ticker")
            for col in records.columns:
                if col not in skip_cols:
                    records[col] = records[col].map(parse_number)
            if period_col != "period":
                records = records.rename(columns={period_col: "period"})
            if ticker_col is not None and ticker_col != "ticker":
                records = records.rename(columns={ticker_col: "ticker"})
            return records

        # Wide format: first column is the metric name, remaining columns are periods.
        metric_col = df.columns[0]
        period_cols = list(df.columns[1:])
        records = []
        ticker = self._infer_ticker(file_path)
        for period in period_cols:
            record = {"ticker": ticker, "period": str(period)}
            for _, row in df.iterrows():
                metric_name = row.get(metric_col)
                if pd.isna(metric_name):
                    continue
                record[str(metric_name)] = parse_number(row.get(period))
            records.append(record)

        return pd.DataFrame(records)

    def _load_csv(self, file_path: str) -> pd.DataFrame:
        try:
            df = pd.read_csv(file_path)
            return self._normalize_tabular_columns(df, file_path)
        except Exception:
            logger.exception("Error loading CSV file: %s", file_path)
            return None

    def _load_excel(self, file_path: str) -> pd.DataFrame:
        try:
            sheets = pd.read_excel(file_path, sheet_name=None)
            frames = []
            for _, sheet_df in sheets.items():
                normalized = self._normalize_tabular_columns(sheet_df, file_path)
                if normalized is not None and not normalized.empty:
                    frames.append(normalized)
            if not frames:
                return pd.DataFrame()
            return pd.concat(frames, ignore_index=True)
        except Exception:
            logger.exception("Error loading Excel file: %s", file_path)
            return None
