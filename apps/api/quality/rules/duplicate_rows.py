from typing import List, Dict, Any
import pandas as pd

from ..rule import QualityRule
from ..result import RuleResult


class DuplicateRowsRule(QualityRule):
    name = "duplicate_rows"
    description = "Detects fully duplicate rows"
    default_severity = "WARNING"
    issue_type = "DUPLICATE_ROWS"

    def evaluate(self, df: pd.DataFrame, context: Dict[str, Any]) -> List[RuleResult]:
        total_rows = len(df)
        if total_rows == 0:
            return []
        entire_dupes = int(df.duplicated().sum())
        if entire_dupes > 0:
            pct = round((entire_dupes / total_rows) * 100, 2)
            return [
                self._result(
                    severity="WARNING",
                    column_name=None,
                    description=f"Dataset contains {entire_dupes} ({pct}%) completely duplicate rows.",
                    metadata={"duplicate_rows": entire_dupes, "duplicate_pct": pct},
                    issue_type="DUPLICATE_ROWS",
                    affected_columns=[],
                )
            ]
        return []
