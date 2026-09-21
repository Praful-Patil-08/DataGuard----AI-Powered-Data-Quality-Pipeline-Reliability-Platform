from typing import List, Dict, Any
import pandas as pd

from ..rule import QualityRule
from ..result import RuleResult


class CategoricalConsistencyRule(QualityRule):
    name = "categorical_consistency"
    description = "Detects inconsistent categorical casing/variants"
    default_severity = "WARNING"
    issue_type = "CATEGORICAL_INCONSISTENCY"

    def __init__(self, max_unique: int = 20):
        self.max_unique = max_unique

    def evaluate(self, df: pd.DataFrame, context: Dict[str, Any]) -> List[RuleResult]:
        results = []
        for col in df.columns:
            series = df[col]
            if not (series.dtype == object or series.dtype == "string"):
                continue
            str_vals = series.dropna().astype(str).tolist()
            if len(str_vals) == 0 or len(set(str_vals)) > self.max_unique:
                continue
            lowered_map = {}
            inconsistent_groups = []
            for val in set(str_vals):
                low = val.strip().lower()
                lowered_map.setdefault(low, set()).add(val)
            for low, variations in lowered_map.items():
                if len(variations) > 1:
                    inconsistent_groups.append(list(variations))
            if inconsistent_groups:
                results.append(
                    self._result(
                        severity="WARNING",
                        column_name=col,
                        description=f"Column '{col}' has inconsistent categorical casings/variants: {inconsistent_groups[0]}.",
                        metadata={"inconsistent_variants": inconsistent_groups},
                        issue_type="CATEGORICAL_INCONSISTENCY",
                        affected_columns=[col],
                    )
                )
        return results
