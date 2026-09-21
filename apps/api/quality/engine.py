from typing import List, Dict, Any, Optional
import pandas as pd

from .registry import QualityRuleRegistry
from .result import RuleResult
from .rules.empty_dataset import EmptyDatasetRule
from .rules.primary_key import PrimaryKeyRule
from .rules.duplicate_rows import DuplicateRowsRule
from .rules.null_rate import NullRateRule
from .rules.negative_value import NegativeValueRule
from .rules.numeric_anomaly import NumericAnomalyRule
from .rules.date_validation import DateValidationRule
from .rules.categorical_consistency import CategoricalConsistencyRule


def _resolve_primary_keys(
    dataset_name: Optional[str],
    primary_key_candidates: Optional[List[str]],
    df: pd.DataFrame,
) -> List[str]:
    """
    Resolve PK candidates contract-aware (mirrors original quality.py).
    Precedence: explicit candidates > contract > heuristic fallback.
    """
    if primary_key_candidates is not None:
        return primary_key_candidates

    if dataset_name:
        try:
            from contracts import get_primary_key_columns

            pk = get_primary_key_columns(dataset_name)
            if pk is None:
                return []  # fact/dimension/no PK enforcement
            return pk
        except Exception:
            return []

    # Backward compat: no dataset_name → heuristic (legacy tests)
    return [c for c in df.columns if c.lower().endswith("_id") or c.lower() == "id"]


def build_default_registry(
    null_threshold: Optional[float] = None,  # kept for compat but not used directly
    outlier_std_multiplier: float = 3.0,
) -> QualityRuleRegistry:
    """
    Build registry with all default rules in original execution order.
    This order matches the original monolithic quality.py sequencing so
    that issue output order stays stable for tests/snapshots.
    """
    registry = QualityRuleRegistry()
    registry.register(EmptyDatasetRule())
    registry.register(PrimaryKeyRule())
    registry.register(DuplicateRowsRule())
    registry.register(NullRateRule())
    registry.register(NegativeValueRule())
    registry.register(NumericAnomalyRule(std_multiplier=outlier_std_multiplier))
    registry.register(DateValidationRule())
    registry.register(CategoricalConsistencyRule())
    return registry


# Singleton default registry (extensible via add/remove)
_default_registry: Optional[QualityRuleRegistry] = None


def get_default_registry() -> QualityRuleRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = build_default_registry()
    return _default_registry


class QualityEngine:
    """
    Deterministic quality engine — orchestrates ordered rule execution.
    Inspired by Great Expectations Validator + Soda scan executor.

    Design:
    - Rules never mutate df
    - Engine resolves context (PK, thresholds) once and passes to all rules
    - Short-circuit: EmptyDatasetRule returns alone if triggered (no other checks make sense)
    """

    def __init__(self, registry: Optional[QualityRuleRegistry] = None):
        self.registry = registry or get_default_registry()

    def run(
        self,
        df: pd.DataFrame,
        dataset_name: Optional[str] = None,
        primary_key_candidates: Optional[List[str]] = None,
        null_threshold: float = 0.0,  # kept for signature compat
        outlier_std_multiplier: float = 3.0,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        total_rows = len(df)

        # Handle legacy positional misuse: dataset_name as list
        if isinstance(dataset_name, list):
            primary_key_candidates = dataset_name
            dataset_name = None

        # Resolve PK candidates contract-aware
        pks = _resolve_primary_keys(dataset_name, primary_key_candidates, df)

        context: Dict[str, Any] = {
            "dataset_name": dataset_name,
            "primary_key_candidates": pks,
            "null_threshold": null_threshold,
            "outlier_std_multiplier": outlier_std_multiplier,
            "total_rows": total_rows,
        }
        if extra_context:
            context.update(extra_context)

        # Empty dataset is terminal — matches original early return
        if total_rows == 0:
            # Evaluate only EmptyDatasetRule to preserve original exact output
            from .rules.empty_dataset import EmptyDatasetRule as ERule

            r = ERule()
            if r.is_applicable(df, context):
                results = r.evaluate(df, context)
                return [res.to_issue_dict() for res in results]
            return []

        all_results: List[RuleResult] = []
        for rule in self.registry.all_rules():
            # Skip empty_dataset when not empty (already handled)
            if rule.name == "empty_dataset" and total_rows != 0:
                continue
            if not rule.is_applicable(df, context):
                continue
            try:
                res = rule.evaluate(df, context)
                all_results.extend(res)
            except Exception as e:
                # Fail-safe: a single rule failure must not break scan
                # (mirrors main.py's try wrapper but at finer grain)
                # We surface as WARNING so operators can see it
                all_results.append(
                    RuleResult(
                        rule_name=rule.name,
                        issue_type="RULE_EXECUTION_ERROR",
                        severity="WARNING",
                        column_name=None,
                        description=f"Rule '{rule.name}' failed: {str(e)[:120]}",
                        metadata={"error": str(e)[:300], "rule": rule.name},
                    )
                )

        # Convert to legacy dict shape expected by main.py / tests
        return [r.to_issue_dict() for r in all_results]


# Functional façade — preserves original `from quality import run_quality_checks` signature
_default_engine = QualityEngine()


def run_quality_checks(
    df: pd.DataFrame,
    dataset_name: str = None,
    primary_key_candidates: List[str] = None,
    null_threshold: float = 0.0,
    outlier_std_multiplier: float = 3.0,
) -> List[Dict[str, Any]]:
    # Handle legacy positional misuse (dataset_name as list)
    if isinstance(dataset_name, list):
        primary_key_candidates = dataset_name
        dataset_name = None

    return _default_engine.run(
        df,
        dataset_name=dataset_name,
        primary_key_candidates=primary_key_candidates,
        null_threshold=null_threshold,
        outlier_std_multiplier=outlier_std_multiplier,
    )
