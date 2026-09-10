import io
import hashlib
import math
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple

def parse_dataset_content(content: bytes, filename: str) -> pd.DataFrame:
    """Parses raw uploaded bytes into a pandas DataFrame based on file type."""
    ext = filename.lower().split(".")[-1]
    if ext == "csv":
        try:
            return pd.read_csv(io.BytesIO(content))
        except Exception as e:
            raise ValueError(f"Malformed CSV file: {str(e)}")
    elif ext == "json":
        try:
            # Try reading as standard JSON array or JSON lines
            try:
                return pd.read_json(io.BytesIO(content))
            except ValueError:
                return pd.read_json(io.BytesIO(content), lines=True)
        except Exception as e:
            raise ValueError(f"Malformed JSON file: {str(e)}")
    else:
        raise ValueError(f"Unsupported file extension: {ext}. Only CSV and JSON are supported.")

def infer_column_datatype(series: pd.Series) -> str:
    """
    Deterministically infers high-level data type:
    INTEGER, FLOAT, DATE, BOOLEAN, or STRING.
    """
    non_null = series.dropna()
    if len(non_null) == 0:
        return "STRING"

    # Check Boolean
    if pd.api.types.is_bool_dtype(series):
        return "BOOLEAN"
    
    # Check Integer
    if pd.api.types.is_integer_dtype(series):
        return "INTEGER"
    
    # Check Float
    if pd.api.types.is_float_dtype(series):
        return "FLOAT"

    # Check Date / Datetime
    if pd.api.types.is_datetime64_any_dtype(series):
        return "DATE"

    # Try numeric conversion if stored as object/string
    if series.dtype == object or series.dtype == "string":
        # Check if dates
        try:
            sample = non_null.head(20).astype(str)
            if not all(s.replace(".", "", 1).replace("-", "", 1).isdigit() for s in sample):
                pd.to_datetime(sample, format="mixed", errors="raise")
                return "DATE"
        except Exception:
            pass

        # Try Integer
        try:
            int_vals = pd.to_numeric(non_null, downcast="integer", errors="raise")
            if (int_vals % 1 == 0).all():
                return "INTEGER"
            return "FLOAT"
        except Exception:
            pass

        # Check if float
        try:
            pd.to_numeric(non_null, errors="raise")
            return "FLOAT"
        except Exception:
            pass

    return "STRING"

def _percentile(values: List[float], fraction: float) -> float:
    """Linear percentile - adapted from Watchtower watchtower.py:614"""
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * fraction
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return values[lower_index]
    lower_value = values[lower_index]
    upper_value = values[upper_index]
    return lower_value + (upper_value - lower_value) * (position - lower_index)

def _numeric_summary(values: List[float]) -> Dict[str, Any]:
    """Computes numeric summary with IQR outlier detection - adapted from Watchtower _numeric_summary:593"""
    numbers = [float(v) for v in values]
    ordered = sorted(numbers)
    q1 = _percentile(ordered, 0.25)
    q3 = _percentile(ordered, 0.75)
    iqr = q3 - q1
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr
    outlier_count = sum(1 for v in numbers if v < lower_fence or v > upper_fence)
    return {
        "min_value": round(min(numbers), 3) if numbers else 0.0,
        "max_value": round(max(numbers), 3) if numbers else 0.0,
        "mean": round(sum(numbers) / len(numbers), 3) if numbers else 0.0,
        "median": round(_percentile(ordered, 0.5), 3) if numbers else 0.0,
        "p05": round(_percentile(ordered, 0.05), 3) if numbers else 0.0,
        "p95": round(_percentile(ordered, 0.95), 3) if numbers else 0.0,
        "outlier_count": outlier_count,
        "outlier_rate": round(outlier_count / len(numbers), 3) if numbers else 0.0,
    }

def _top_values(series: pd.Series, row_count: int) -> List[Dict[str, Any]]:
    """Computes top 3 most frequent values - adapted from Watchtower _top_values:561"""
    non_null = series.dropna().astype(str)
    counts: Dict[str, int] = {}
    for val in non_null:
        counts[val] = counts.get(val, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"value": key, "count": count, "rate": round(count / row_count, 3) if row_count else 0.0}
        for key, count in ordered[:3]
    ]

def _clean_sample_values(values) -> List[Any]:
    clean = []
    for val in values:
        if isinstance(val, (np.integer, int)):
            clean.append(int(val))
        elif isinstance(val, (np.floating, float)):
            # Handle NaN
            if pd.isna(val):
                continue
            clean.append(float(val))
        elif isinstance(val, (np.bool_, bool)):
            clean.append(bool(val))
        else:
            clean.append(str(val))
    return clean

def profile_dataframe(df: pd.DataFrame) -> Tuple[List[Dict[str, Any]], str]:
    """
    Deterministically profiles all columns in a dataframe and computes
    a SHA256 schema fingerprint.
    Enhanced with Watchtower profiling: null_rate, unique_ratio, numeric stats, top_values.
    """
    column_profiles = []
    fingerprint_elements = []
    row_count = len(df)

    for col in df.columns:
        series = df[col]
        data_type = infer_column_datatype(series)
        null_count = int(series.isna().sum())
        nullable = null_count > 0
        unique_count = int(series.nunique(dropna=True))
        null_rate = round(null_count / row_count, 3) if row_count else 0.0
        unique_ratio = round(unique_count / row_count, 3) if row_count else 0.0

        # 5 sample non-null values
        sample_vals = series.dropna().unique()[:5].tolist()
        clean_samples = _clean_sample_values(sample_vals)

        # Top values (frequency) - for all columns
        top_vals = _top_values(series, row_count)

        # Numeric summary for INTEGER/FLOAT
        numeric_summary = None
        mean = median = p05 = p95 = min_val = max_val = None
        outlier_count = 0
        outlier_rate = 0.0
        if data_type in ("INTEGER", "FLOAT"):
            numeric_series = pd.to_numeric(series, errors="coerce").dropna()
            if len(numeric_series) > 0:
                try:
                    numeric_vals = numeric_series.astype(float).tolist()
                    summary = _numeric_summary(numeric_vals)
                    min_val = summary["min_value"]
                    max_val = summary["max_value"]
                    mean = summary["mean"]
                    median = summary["median"]
                    p05 = summary["p05"]
                    p95 = summary["p95"]
                    outlier_count = summary["outlier_count"]
                    outlier_rate = summary["outlier_rate"]
                    numeric_summary = summary
                except Exception:
                    numeric_summary = None

        profile = {
            "column_name": str(col),
            "data_type": data_type,
            "nullable": nullable,
            "null_count": null_count,
            "null_rate": null_rate,
            "unique_count": unique_count,
            "unique_ratio": unique_ratio,
            "sample_values": clean_samples,
            "top_values": top_vals,
            # Flattened numeric fields for DB persistence
            "min_value": min_val,
            "max_value": max_val,
            "mean": mean,
            "median": median,
            "p05": p05,
            "p95": p95,
            "outlier_count": outlier_count,
            "outlier_rate": outlier_rate,
            "_numeric_summary": numeric_summary,
        }
        column_profiles.append(profile)
        fingerprint_elements.append(f"{col}:{data_type}:{nullable}")

    # Generate deterministic fingerprint (sorted for stability)
    fingerprint_elements.sort()
    raw_signature = "|".join(fingerprint_elements)
    fingerprint = hashlib.sha256(raw_signature.encode("utf-8")).hexdigest()

    return column_profiles, fingerprint
