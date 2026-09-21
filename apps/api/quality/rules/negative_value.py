from typing import List, Dict, Any
import pandas as pd

from ..rule import QualityRule
from ..result import RuleResult


class NegativeValueRule(QualityRule):
    name = "negative_value"
    description = "Detects negative values in financial/positive columns"
    default_severity = "CRITICAL"
    issue_type = "NEGATIVE_VALUE_ANOMALY"

    def evaluate(self, df: pd.DataFrame, context: Dict[str, Any]) -> List[RuleResult]:
        results = []
        for col in df.columns:
            col_lower = col.lower()
            if not any(k in col_lower for k in ("value", "price", "cost", "amount")):
                continue
            series = df[col]
            numeric_series = pd.to_numeric(series, errors="coerce")
            if numeric_series.notna().sum() == 0:
                continue
            negative_count = int((numeric_series < 0).sum())
            if negative_count > 0:
                results.append(
                    self._result(
                        severity="CRITICAL",
                        column_name=col,
                        description=f"Financial/positive column '{col}' contains {negative_count} negative values.",
                        metadata={"negative_count": negative_count},
                        issue_type="NEGATIVE_VALUE_ANOMALY",
                        affected_columns=[col],
                    )
                )
        return results
