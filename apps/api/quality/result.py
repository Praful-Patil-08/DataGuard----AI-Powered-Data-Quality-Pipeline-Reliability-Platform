from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


@dataclass
class RuleResult:
    """
    Structured result from a single QualityRule evaluation.
    Maps 1:1 to the Issue dict persisted in main.py (Issue row).
    Inspired by Great Expectations ValidationResult + Soda check result.
    """
    rule_name: str
    issue_type: str
    severity: str  # CRITICAL | WARNING | INFO
    column_name: Optional[str]
    description: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Extensible evidence fields (Phase 1 minimal, future: samples, thresholds)
    evidence: Dict[str, Any] = field(default_factory=dict)
    affected_columns: List[str] = field(default_factory=list)

    def to_issue_dict(self) -> Dict[str, Any]:
        """Convert to the dict shape expected by main.py → Issue model."""
        return {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "column_name": self.column_name,
            "description": self.description,
            "metadata": self.metadata,
        }
