from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import pandas as pd

from .result import RuleResult


class QualityRule(ABC):
    """
    Base contract for deterministic quality checks.
    Inspired by Great Expectations Expectation + Soda check contract.

    Each rule is:
    - self-contained (no hidden side effects)
    - deterministic (same df + config → same results)
    - explainable (rule_name + description + evidence)
    - testable in isolation
    """

    # Unique identifier, also used as registry key
    name: str = "base_rule"
    # Human-readable description of what the rule checks
    description: str = "Base quality rule"
    # Default severity if not overridden per evaluation
    default_severity: str = "WARNING"
    # issue_type emitted (maps to Issue.issue_type)
    issue_type: str = "UNKNOWN"

    def is_applicable(self, df: pd.DataFrame, context: Dict[str, Any]) -> bool:
        """Return False to skip this rule for the given df/context."""
        return True

    @abstractmethod
    def evaluate(self, df: pd.DataFrame, context: Dict[str, Any]) -> List[RuleResult]:
        """Execute the rule deterministically; return 0-N results."""
        raise NotImplementedError

    # Small helper to build RuleResult with consistent shape
    def _result(
        self,
        severity: str,
        column_name: Optional[str],
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
        evidence: Optional[Dict[str, Any]] = None,
        issue_type: Optional[str] = None,
        affected_columns: Optional[List[str]] = None,
    ) -> RuleResult:
        return RuleResult(
            rule_name=self.name,
            issue_type=issue_type or self.issue_type,
            severity=severity,
            column_name=column_name,
            description=description,
            metadata=metadata or {},
            evidence=evidence or {},
            affected_columns=affected_columns or ([column_name] if column_name else []),
        )
