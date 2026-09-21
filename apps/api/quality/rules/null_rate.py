from typing import List, Dict, Any
import pandas as pd

from ..rule import QualityRule
from ..result import RuleResult


class NullRateRule(QualityRule):
    """
    Column-level null-rate check.
    Flags HIGH_NULL_RATE when >5% (WARNING) or >=20% (CRITICAL).
    Skips PK columns (already covered by PrimaryKeyRule).
    """

    name = "null_rate"
    description = "Flags columns with high null rates"
    default_severity = "WARNING"
    issue_type = "HIGH_NULL_RATE"

    def __init__(self, warning_threshold: float = 5.0, critical_threshold: float = 20.0):
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold

    def evaluate(self, df: pd.DataFrame, context: Dict[str, Any]) -> List[RuleResult]:
        results = []
        total_rows = len(df)
        if total_rows == 0:
            return results
        pks = set(context.get("primary_key_candidates") or [])
        for col in df.columns:
            if col in pks:
                continue
            series = df[col]
            null_count = int(series.isna().sum())
            null_pct = round((null_count / total_rows) * 100, 2) if total_rows else 0.0
            if null_pct > self.warning_threshold:
                severity = "CRITICAL" if null_pct >= self.critical_threshold else "WARNING"
                results.append(
                    self._result(
                        severity=severity,
                        column_name=col,
                        description=f"Column '{col}' has a high null rate of {null_pct}% ({null_count}/{total_rows}).",
                        metadata={"null_count": null_count, "null_pct": null_pct},
                        issue_type="HIGH_NULL_RATE",
                        affected_columns=[col],
                    )
                )
        return results
