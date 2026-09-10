from typing import List, Dict, Any, Set
import os
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "lineage_config.json"

# Standard Lineage Graph for E-commerce / D2C Analytics (fallback)
DEFAULT_LINEAGE_MAP = {
    # Column -> list of downstream assets (model or dashboard)
    "orders.order_value": [
        {"name": "revenue_model", "asset_type": "SQL_MODEL", "relationship": "DIRECT_INPUT"},
        {"name": "monthly_revenue", "asset_type": "SQL_MODEL", "relationship": "ROLLUP_AGGREGATION"},
        {"name": "customer_ltv", "asset_type": "SQL_MODEL", "relationship": "METRIC_CALCULATION"},
        {"name": "Executive Revenue Dashboard", "asset_type": "DASHBOARD", "relationship": "KPI_REPORT"}
    ],
    "orders.order_amount": [
        {"name": "revenue_model", "asset_type": "SQL_MODEL", "relationship": "POTENTIAL_MAPPING"},
        {"name": "Executive Revenue Dashboard", "asset_type": "DASHBOARD", "relationship": "KPI_REPORT"}
    ],
    "orders.customer_id": [
        {"name": "customer_360_view", "asset_type": "SQL_MODEL", "relationship": "PRIMARY_JOIN_KEY"},
        {"name": "cohort_retention_analysis", "asset_type": "SQL_MODEL", "relationship": "GROUPING_KEY"},
        {"name": "Customer Insights Dashboard", "asset_type": "DASHBOARD", "relationship": "USER_SEGMENTATION"}
    ],
    "orders.discount": [
        {"name": "margin_analysis_model", "asset_type": "SQL_MODEL", "relationship": "PROFITABILITY_CALC"},
        {"name": "Promotion ROI Dashboard", "asset_type": "DASHBOARD", "relationship": "DISCOUNT_EFFECTIVENESS"}
    ],
    "orders.order_date": [
        {"name": "daily_sales_summary", "asset_type": "SQL_MODEL", "relationship": "PARTITION_TIMESTAMP"},
        {"name": "Executive Revenue Dashboard", "asset_type": "DASHBOARD", "relationship": "TIME_SERIES_FILTER"}
    ],
    "customers.signup_date": [
        {"name": "cohort_retention_analysis", "asset_type": "SQL_MODEL", "relationship": "COHORT_ANCHOR"},
        {"name": "Marketing Attribution Dashboard", "asset_type": "DASHBOARD", "relationship": "ACQUISITION_TIMELINE"}
    ],
    "products.price": [
        {"name": "gross_merchandise_value", "asset_type": "SQL_MODEL", "relationship": "PRICE_CALCULATION"},
        {"name": "Pricing Optimization Dashboard", "asset_type": "DASHBOARD", "relationship": "PRICING_BENCHMARK"}
    ]
}

def _load_config() -> Dict[str, Any]:
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return DEFAULT_LINEAGE_MAP

def get_lineage_config() -> Dict[str, Any]:
    return _load_config()

def is_demo_lineage(dataset_name: str, column_name: str) -> bool:
    # For MVP, all lineage is demo — flag true unless config is explicitly marked production
    cfg = _load_config()
    clean_ds = dataset_name.lower().replace(".csv", "").replace(".json", "")
    key = f"{clean_ds}.{column_name.lower()}"
    # If key is in default and not overridden, it's demo; if file edited, still demo until OpenLineage integrated
    return True

def get_downstream_impact(dataset_name: str, column_name: str) -> List[Dict[str, str]]:
    """
    Traces downstream SQL models and BI dashboards affected by a given dataset column.
    Uses editable lineage_config.json if present, else DEFAULT_LINEAGE_MAP.
    """
    clean_ds = dataset_name.lower().replace(".csv", "").replace(".json", "")
    key = f"{clean_ds}.{column_name.lower()}"
    cfg = _load_config()
    if key in cfg:
        return cfg[key]

    # Heuristic fallback if not in explicit lineage map
    inferred_assets = []
    col_lower = column_name.lower()
    if "id" in col_lower:
        inferred_assets.append({
            "name": f"{clean_ds}_joined_view",
            "asset_type": "SQL_MODEL",
            "relationship": "JOIN_KEY_DEPENDENCY"
        })
    elif "date" in col_lower or "time" in col_lower:
        inferred_assets.append({
            "name": f"{clean_ds}_daily_metrics",
            "asset_type": "SQL_MODEL",
            "relationship": "TEMPORAL_PARTITION"
        })
    else:
        inferred_assets.append({
            "name": f"{clean_ds}_staging_model",
            "asset_type": "SQL_MODEL",
            "relationship": "COLUMN_TRANSFORMATION"
        })
        inferred_assets.append({
            "name": f"{clean_ds.capitalize()} Analytics Dashboard",
            "asset_type": "DASHBOARD",
            "relationship": "REPORT_VIEW"
        })

    return inferred_assets
