from typing import List, Dict, Any
import pandas as pd

from ..rule import QualityRule
from ..result import RuleResult


class PrimaryKeyRule(QualityRule):
    """
    Validates primary-key invariants:
    - No NULLs in PK columns
    - No duplicates (including composite PK)

    Contract-aware: PK columns resolved by engine via contracts.py; not heuristic.
    Emits PRIMARY_KEY_NULL and DUPLICATE_PRIMARY_KEY.
    """

    name = "primary_key"
    description = "Validates primary-key null and uniqueness guarantees"
    default_severity = "CRITICAL"

    def evaluate(self, df: pd.DataFrame, context: Dict[str, Any]) -> List[RuleResult]:
        results: List[RuleResult] = []
        total_rows = len(df)
        pks: List[str] = context.get("primary_key_candidates") or []

        if not pks:
            return results

        # Composite PK handling (mirrors original quality.py composite branch)
        if len(pks) > 1 and all(col in df.columns for col in pks):
            # Null: any key column null in a row
            composite_null = int(df[pks].isna().any(axis=1).sum())
            if composite_null > 0:
                pct = round((composite_null / total_rows) * 100, 2) if total_rows else 0.0
                col_label = ", ".join(pks)
                results.append(
                    self._result(
                        severity="CRITICAL",
                        column_name=col_label,
                        description=f"Composite primary key ({', '.join(pks)}) contains {composite_null} ({pct}%) rows with NULL in key columns.",
                        metadata={"null_count": composite_null, "null_pct": pct, "columns": pks},
                        issue_type="PRIMARY_KEY_NULL",
                        affected_columns=pks,
                    )
                )
            # Duplicates: duplicate combinations (only among non-null tuples)
            non_null_composite = df.dropna(subset=pks)
            dupe_count = int(non_null_composite.duplicated(subset=pks).sum())
            if dupe_count > 0:
                pct = round((dupe_count / total_rows) * 100, 2) if total_rows else 0.0
                col_label = ", ".join(pks)
                results.append(
                    self._result(
                        severity="CRITICAL",
                        column_name=col_label,
                        description=f"Composite primary key ({', '.join(pks)}) has {dupe_count} ({pct}%) duplicate combinations.",
                        metadata={"duplicate_count": dupe_count, "duplicate_pct": pct, "columns": pks},
                        issue_type="DUPLICATE_PRIMARY_KEY",
                        affected_columns=pks,
                    )
                )
            return results

        # Single-column PKs (including single of composite fallback)
        for pk_col in pks:
            if pk_col not in df.columns:
                continue
            series = df[pk_col]
            null_count = int(series.isna().sum())
            if null_count > 0:
                pct = round((null_count / total_rows) * 100, 2) if total_rows else 0.0
                results.append(
                    self._result(
                        severity="CRITICAL",
                        column_name=pk_col,
                        description=f"Primary key/ID column '{pk_col}' contains {null_count} ({pct}%) NULL values.",
                        metadata={"null_count": null_count, "null_pct": pct},
                        issue_type="PRIMARY_KEY_NULL",
                        affected_columns=[pk_col],
                    )
                )
            non_null = series.dropna()
            dupe_count = int(non_null.duplicated().sum())
            if dupe_count > 0:
                pct = round((dupe_count / total_rows) * 100, 2) if total_rows else 0.0
                results.append(
                    self._result(
                        severity="CRITICAL",
                        column_name=pk_col,
                        description=f"Primary key/ID column '{pk_col}' has {dupe_count} ({pct}%) duplicate values.",
                        metadata={"duplicate_count": dupe_count, "duplicate_pct": pct},
                        issue_type="DUPLICATE_PRIMARY_KEY",
                        affected_columns=[pk_col],
                    )
                )
        return results
