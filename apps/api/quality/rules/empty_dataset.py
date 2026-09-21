from typing import List, Dict, Any
import pandas as pd

from ..rule import QualityRule
from ..result import RuleResult


class EmptyDatasetRule(QualityRule):
    name = "empty_dataset"
    description = "Detects datasets with zero rows"
    default_severity = "CRITICAL"
    issue_type = "EMPTY_DATASET"

    def evaluate(self, df: pd.DataFrame, context: Dict[str, Any]) -> List[RuleResult]:
        if len(df) == 0:
            return [
                self._result(
                    severity="CRITICAL",
                    column_name=None,
                    description="The dataset contains 0 rows.",
                    metadata={},
                    issue_type="EMPTY_DATASET",
                    affected_columns=[],
                )
            ]
        return []
