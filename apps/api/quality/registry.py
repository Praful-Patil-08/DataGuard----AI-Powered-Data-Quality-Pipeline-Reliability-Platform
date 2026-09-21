from typing import Dict, List, Type, Optional
from .rule import QualityRule


class QualityRuleRegistry:
    """
    Registry for QualityRules — Soda-like check registry / GE expectation registry.
    Supports:
    - programmatic registration
    - ordered iteration (insertion order = execution order)
    - lookup by name
    """

    def __init__(self):
        self._rules: Dict[str, QualityRule] = {}
        self._order: List[str] = []

    def register(self, rule: QualityRule) -> None:
        """Register an instantiated rule. Overwrites if name exists (warn not fail)."""
        if rule.name in self._rules:
            # overwrite but preserve order
            self._rules[rule.name] = rule
            return
        self._rules[rule.name] = rule
        self._order.append(rule.name)

    def register_class(self, rule_cls: Type[QualityRule], *args, **kwargs) -> QualityRule:
        """Instantiate and register a rule class."""
        inst = rule_cls(*args, **kwargs)
        self.register(inst)
        return inst

    def get(self, name: str) -> Optional[QualityRule]:
        return self._rules.get(name)

    def all_rules(self) -> List[QualityRule]:
        return [self._rules[n] for n in self._order]

    def names(self) -> List[str]:
        return list(self._order)

    def clear(self) -> None:
        self._rules.clear()
        self._order.clear()

    def __len__(self) -> int:
        return len(self._rules)

    def __contains__(self, name: str) -> bool:
        return name in self._rules
