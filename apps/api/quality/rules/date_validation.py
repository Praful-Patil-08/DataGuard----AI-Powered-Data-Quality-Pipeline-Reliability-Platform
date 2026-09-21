from typing import List, Dict, Any
import pandas as pd

from ..rule import QualityRule
from ..result import RuleResult


class DateValidationRule(QualityRule):
    name = "date_validation"
    description = "Detects malformed date strings in date/time columns"
    default_severity = "CRITICAL"
    issue_type = "MALFORMED_DATE"

    def evaluate(self, df: pd.DataFrame, context: Dict[str, Any]) -> List[RuleResult]:
        results = []
        for col in df.columns:
            col_lower = col.lower()
            if "date" not in col_lower and "time" not in col_lower:
                continue
            series = df[col]
            non_null_vals = series.dropna().astype(str)
            invalid_dates = []
            for val in non_null_vals:
                try:
                    pd.to_datetime(val)
                except Exception:
                    invalid_dates.append(val)
            if invalid_dates:
                results.append(
                    self._result(
                        severity="CRITICAL",
                        column_name=col,
                        description=f"Date column '{col}' contains {len(invalid_dates)} malformed date strings (e.g. '{invalid_dates[0]}').",
                        metadata={"invalid_count": len(invalid_dates), "sample": invalid_dates[:3]},
                        issue_type="MALFORMED_DATE",
                        affected_columns=[col],
                    )
                )
        return results
