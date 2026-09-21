from typing import List, Dict, Any
import pandas as pd
import numpy as np

from ..rule import QualityRule
from ..result import RuleResult


class NumericAnomalyRule(QualityRule):
    name = "numeric_anomaly"
    description = "Detects statistical outliers beyond N std deviations (z-score)"
    default_severity = "WARNING"
    issue_type = "NUMERIC_ANOMALY"

    def __init__(self, std_multiplier: float = 3.0, min_valid: int = 5):
        self.std_multiplier = std_multiplier
        self.min_valid = min_valid

    def evaluate(self, df: pd.DataFrame, context: Dict[str, Any]) -> List[RuleResult]:
        multiplier = context.get("outlier_std_multiplier", self.std_multiplier)
        results = []
        for col in df.columns:
            series = df[col]
            numeric_series = pd.to_numeric(series, errors="coerce")
            valid_nums = numeric_series.dropna()
            if len(valid_nums) < self.min_valid:
                continue
            mean = valid_nums.mean()
            std = valid_nums.std()
            if std is None or std == 0 or np.isnan(std):
                continue
            outliers = valid_nums[np.abs(valid_nums - mean) > multiplier * std]
            if len(outliers) > 0:
                sample_outliers = outliers.head(3).tolist()
                results.append(
                    self._result(
                        severity="WARNING",
                        column_name=col,
                        description=f"Column '{col}' has {len(outliers)} statistical outlier value(s) beyond {multiplier} standard deviations (samples: {sample_outliers}).",
                        metadata={"outlier_count": len(outliers), "samples": sample_outliers, "mean": round(float(mean), 2)},
                        issue_type="NUMERIC_ANOMALY",
                        affected_columns=[col],
                    )
                )
        return results
