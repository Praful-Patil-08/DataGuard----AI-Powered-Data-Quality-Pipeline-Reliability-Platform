import pandas as pd
import numpy as np
from typing import List, Dict, Any

def run_quality_checks(
    df: pd.DataFrame,
    primary_key_candidates: List[str] = None,
    null_threshold: float = 0.0, # Flag any null in key fields or >5% in others
    outlier_std_multiplier: float = 3.0
) -> List[Dict[str, Any]]:
    """
    Executes deterministic data quality checks on a DataFrame.
    Returns a list of structured issue dictionaries.
    """
    issues = []
    total_rows = len(df)
    if total_rows == 0:
        return [{
            "issue_type": "EMPTY_DATASET",
            "severity": "CRITICAL",
            "column_name": None,
            "description": "The dataset contains 0 rows.",
            "metadata": {}
        }]

    # Auto-detect likely primary key candidates if not specified
    if not primary_key_candidates:
        primary_key_candidates = [
            c for c in df.columns if c.lower().endswith("_id") or c.lower() == "id"
        ]

    # 1. Primary Key and ID Checks (Duplicate & Null)
    for pk_col in primary_key_candidates:
        if pk_col in df.columns:
            series = df[pk_col]
            # Null check on primary key
            null_count = int(series.isna().sum())
            if null_count > 0:
                pct = round((null_count / total_rows) * 100, 2)
                issues.append({
                    "issue_type": "PRIMARY_KEY_NULL",
                    "severity": "CRITICAL",
                    "column_name": pk_col,
                    "description": f"Primary key/ID column '{pk_col}' contains {null_count} ({pct}%) NULL values.",
                    "metadata": {"null_count": null_count, "null_pct": pct}
                })

            # Duplicate check on primary key
            non_null = series.dropna()
            dupe_count = int(non_null.duplicated().sum())
            if dupe_count > 0:
                pct = round((dupe_count / total_rows) * 100, 2)
                issues.append({
                    "issue_type": "DUPLICATE_PRIMARY_KEY",
                    "severity": "CRITICAL",
                    "column_name": pk_col,
                    "description": f"Primary key/ID column '{pk_col}' has {dupe_count} ({pct}%) duplicate values.",
                    "metadata": {"duplicate_count": dupe_count, "duplicate_pct": pct}
                })

    # 2. General Duplicate Rows
    entire_dupes = int(df.duplicated().sum())
    if entire_dupes > 0:
        pct = round((entire_dupes / total_rows) * 100, 2)
        issues.append({
            "issue_type": "DUPLICATE_ROWS",
            "severity": "WARNING",
            "column_name": None,
            "description": f"Dataset contains {entire_dupes} ({pct}%) completely duplicate rows.",
            "metadata": {"duplicate_rows": entire_dupes, "duplicate_pct": pct}
        })

    # 3. Column-by-Column Validations
    for col in df.columns:
        series = df[col]
        # Skip checking nulls again if already reported as critical PK null
        if col not in primary_key_candidates:
            null_count = int(series.isna().sum())
            null_pct = round((null_count / total_rows) * 100, 2)
            if null_pct > 5.0: # Significant null rate
                issues.append({
                    "issue_type": "HIGH_NULL_RATE",
                    "severity": "WARNING" if null_pct < 20 else "CRITICAL",
                    "column_name": col,
                    "description": f"Column '{col}' has a high null rate of {null_pct}% ({null_count}/{total_rows}).",
                    "metadata": {"null_count": null_count, "null_pct": null_pct}
                })

        # 4. Range Check: Negative numeric values where unexpected
        numeric_series = pd.to_numeric(series, errors="coerce")
        if numeric_series.notna().sum() > 0 and (
            "value" in col.lower() or "price" in col.lower() or "cost" in col.lower() or "amount" in col.lower()
        ):
            negative_count = int((numeric_series < 0).sum())
            if negative_count > 0:
                issues.append({
                    "issue_type": "NEGATIVE_VALUE_ANOMALY",
                    "severity": "CRITICAL",
                    "column_name": col,
                    "description": f"Financial/positive column '{col}' contains {negative_count} negative values.",
                    "metadata": {"negative_count": negative_count}
                })

        # 5. Numeric Outlier Check (Z-score / IQR)
        valid_nums = numeric_series.dropna()
        if len(valid_nums) >= 5:
            mean = valid_nums.mean()
            std = valid_nums.std()
            if std > 0:
                outliers = valid_nums[np.abs(valid_nums - mean) > outlier_std_multiplier * std]
                if len(outliers) > 0:
                    sample_outliers = outliers.head(3).tolist()
                    issues.append({
                        "issue_type": "NUMERIC_ANOMALY",
                        "severity": "WARNING",
                        "column_name": col,
                        "description": f"Column '{col}' has {len(outliers)} statistical outlier value(s) beyond {outlier_std_multiplier} standard deviations (samples: {sample_outliers}).",
                        "metadata": {"outlier_count": len(outliers), "samples": sample_outliers, "mean": round(float(mean), 2)}
                    })

        # 6. Date Validation
        if "date" in col.lower() or "time" in col.lower():
            # Check for invalid date strings
            non_null_vals = series.dropna().astype(str)
            invalid_dates = []
            for val in non_null_vals:
                try:
                    pd.to_datetime(val)
                except Exception:
                    invalid_dates.append(val)
            if invalid_dates:
                issues.append({
                    "issue_type": "MALFORMED_DATE",
                    "severity": "CRITICAL",
                    "column_name": col,
                    "description": f"Date column '{col}' contains {len(invalid_dates)} malformed date strings (e.g. '{invalid_dates[0]}').",
                    "metadata": {"invalid_count": len(invalid_dates), "sample": invalid_dates[:3]}
                })

        # 7. Categorical Consistency (casing inconsistency e.g. 'PENDING' vs 'pending')
        if series.dtype == object or series.dtype == "string":
            str_vals = series.dropna().astype(str).tolist()
            if len(str_vals) > 0 and len(set(str_vals)) <= 20: # Categorical candidates
                lowered_map = {}
                inconsistent_groups = []
                for val in set(str_vals):
                    low = val.strip().lower()
                    lowered_map.setdefault(low, set()).add(val)
                for low, variations in lowered_map.items():
                    if len(variations) > 1:
                        inconsistent_groups.append(list(variations))
                if inconsistent_groups:
                    issues.append({
                        "issue_type": "CATEGORICAL_INCONSISTENCY",
                        "severity": "WARNING",
                        "column_name": col,
                        "description": f"Column '{col}' has inconsistent categorical casings/variants: {inconsistent_groups[0]}.",
                        "metadata": {"inconsistent_variants": inconsistent_groups}
                    })

    return issues
