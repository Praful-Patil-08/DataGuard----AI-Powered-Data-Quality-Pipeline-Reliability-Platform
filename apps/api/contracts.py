"""
Dataset Contract — minimal clean abstraction for DataGuard's relational semantics.
Replaces heuristic `endswith _id` with explicit contract.

Contract file: dataset_contracts.json
Keys are dataset names (exact) or prefix (e.g., 'orders' matches 'orders_v1').
Values: { table_type, primary_key: [cols] | null, description }

table_type: entity | fact | event | dimension
primary_key: list of columns that must be unique (composite if len>1), null means no PK enforcement
"""
import json
from pathlib import Path
from typing import List, Optional, Dict, Any

CONTRACT_PATH = Path(__file__).parent / "dataset_contracts.json"

_contracts_cache: Optional[Dict[str, Any]] = None

def load_contracts() -> Dict[str, Any]:
    global _contracts_cache
    if _contracts_cache is not None:
        return _contracts_cache
    try:
        if CONTRACT_PATH.exists():
            _contracts_cache = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        else:
            _contracts_cache = {}
    except Exception:
        _contracts_cache = {}
    return _contracts_cache

def get_contract(dataset_name: str) -> Optional[Dict[str, Any]]:
    """Resolves contract for dataset_name with exact → prefix fallback."""
    if not dataset_name:
        return None
    contracts = load_contracts()
    # exact
    if dataset_name in contracts:
        return contracts[dataset_name]
    # try stripping version suffix like orders_v1, order_items_v1, events_v1
    # also handle olist_ prefix
    lower = dataset_name.lower()
    # direct lower
    if lower in contracts:
        return contracts[lower]
    # prefix before _v or _bad etc: orders_v1 -> orders
    for sep in ["_v", "_bad", "_drift"]:
        if sep in lower:
            prefix = lower.split(sep)[0]
            if prefix in contracts:
                return contracts[prefix]
    # first token before _
    first = lower.split("_")[0]
    if first in contracts:
        return contracts[first]
    # try olist_ name without suffix
    # e.g., olist_customers_dataset_v1 -> olist_customers_dataset
    for key in contracts:
        if lower.startswith(key.lower()):
            return contracts[key]
    return None

def get_primary_key_columns(dataset_name: str) -> Optional[List[str]]:
    c = get_contract(dataset_name)
    if not c:
        return None
    pk = c.get("primary_key")
    if pk is None:
        return None
    if isinstance(pk, str):
        return [pk]
    if isinstance(pk, list):
        return pk
    return None

def is_entity_table(dataset_name: str) -> bool:
    c = get_contract(dataset_name)
    return c is not None and c.get("table_type") == "entity"

def is_fact_or_event_table(dataset_name: str) -> bool:
    c = get_contract(dataset_name)
    return c is not None and c.get("table_type") in ("fact", "event")
