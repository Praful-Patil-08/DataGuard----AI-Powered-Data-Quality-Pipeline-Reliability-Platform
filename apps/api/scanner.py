import io
import json
import hashlib
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
        # If all floats are whole numbers, consider INTEGER if no nulls
        # Otherwise standard FLOAT
        return "FLOAT"

    # Check Date / Datetime
    if pd.api.types.is_datetime64_any_dtype(series):
        return "DATE"

    # Try numeric conversion if stored as object/string
    if series.dtype == object or series.dtype == "string":
        # Check if dates
        try:
            # Check a sample first to avoid slow parser
            sample = non_null.head(20).astype(str)
            # Exclude purely numeric strings from false date conversion
            if not all(s.replace(".", "", 1).isdigit() for s in sample):
                pd.to_datetime(sample, format="mixed", errors="raise")
                return "DATE"
        except Exception:
            pass

        # Try Integer
        try:
            # Check if all can be int
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

def profile_dataframe(df: pd.DataFrame) -> Tuple[List[Dict[str, Any]], str]:
    """
    Deterministically profiles all columns in a dataframe and computes
    a SHA256 schema fingerprint.
    """
    column_profiles = []
    fingerprint_elements = []

    for col in df.columns:
        series = df[col]
        data_type = infer_column_datatype(series)
        null_count = int(series.isna().sum())
        nullable = null_count > 0
        unique_count = int(series.nunique(dropna=True))

        # 5 sample non-null values
        sample_vals = series.dropna().unique()[:5].tolist()
        # Convert numpy/pandas scalars to native Python types for JSON serialization
        clean_samples = []
        for val in sample_vals:
            if isinstance(val, (np.integer, int)):
                clean_samples.append(int(val))
            elif isinstance(val, (np.floating, float)):
                clean_samples.append(float(val))
            elif isinstance(val, (np.bool_, bool)):
                clean_samples.append(bool(val))
            else:
                clean_samples.append(str(val))

        profile = {
            "column_name": str(col),
            "data_type": data_type,
            "nullable": nullable,
            "null_count": null_count,
            "unique_count": unique_count,
            "sample_values": clean_samples,
        }
        column_profiles.append(profile)
        fingerprint_elements.append(f"{col}:{data_type}:{nullable}")

    # Generate deterministic fingerprint
    fingerprint_elements.sort()
    raw_signature = "|".join(fingerprint_elements)
    fingerprint = hashlib.sha256(raw_signature.encode("utf-8")).hexdigest()

    return column_profiles, fingerprint
