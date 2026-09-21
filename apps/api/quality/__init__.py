"""
Quality package — modular rule registry.

Public façade preserves backward compatibility:
    from quality import run_quality_checks
    from quality.engine import QualityEngine, build_default_registry
    from quality.registry import QualityRuleRegistry
    from quality.rule import QualityRule
    from quality.result import RuleResult

Architecture adapted from Great Expectations (Expectations) + Soda Core (checks):
- Great Expectations → typed Expectation per check + Validator orchestrator
- Soda Core → declarative checks + scan/check architecture
DataGuard native implementation: no external dependency, deterministic, testable.
"""

from .engine import run_quality_checks, QualityEngine, build_default_registry, get_default_registry
from .registry import QualityRuleRegistry
from .rule import QualityRule
from .result import RuleResult

__all__ = [
    "run_quality_checks",
    "QualityEngine",
    "build_default_registry",
    "get_default_registry",
    "QualityRuleRegistry",
    "QualityRule",
    "RuleResult",
]
