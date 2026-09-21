"""
Impact Analysis — deterministic downstream propagation (Phase 9).

Uses lineage_graph traversal to answer:
- What is affected? (datasets, pipelines, dashboards)
- How far downstream? (depth/hops)
- Which business KPIs? (Revenue, Customer, Margin, etc.)
- What severity? (propagated with distance decay)

Deterministic, no LLM.

Business KPI mapping (same as main.py business-impact, but consolidated):
"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
import lineage_graph

# Business KPI mapping (maps downstream asset or source column to KPI)
KPI_MAP: Dict[str, Dict[str, str]] = {
    "revenue_model": {"kpi": "Revenue reporting", "description": "Monthly revenue, LTV, Executive Dashboard"},
    "monthly_revenue": {"kpi": "Revenue reporting", "description": "Monthly revenue rollup"},
    "customer_ltv": {"kpi": "Revenue reporting", "description": "Customer LTV model"},
    "Executive Revenue Dashboard": {"kpi": "Revenue reporting", "description": "Executive KPI report"},
    "customer_360_view": {"kpi": "Customer segmentation", "description": "360 view, cohort retention, segmentation"},
    "cohort_retention_analysis": {"kpi": "Customer segmentation", "description": "360 view, cohort retention"},
    "Customer Insights Dashboard": {"kpi": "Customer segmentation", "description": "Customer segmentation UI"},
    "margin_analysis_model": {"kpi": "Margin analysis", "description": "Promotion effectiveness, profitability"},
    "Promotion ROI Dashboard": {"kpi": "Margin analysis", "description": "Promotion effectiveness"},
    "daily_sales_summary": {"kpi": "Revenue reporting", "description": "Daily sales rollup"},
    "gross_merchandise_value": {"kpi": "Margin analysis", "description": "GMV calculation"},
    "Pricing Optimization Dashboard": {"kpi": "Margin analysis", "description": "Pricing benchmark"},
    # Generic fallbacks via keyword
}

def _kpi_for_asset(asset_name: str, source_column: Optional[str] = None, source_dataset: Optional[str] = None) -> Dict[str, str]:
    if asset_name in KPI_MAP:
        return KPI_MAP[asset_name]
    # Heuristic fallback
    name_l = asset_name.lower()
    col_l = (source_column or "").lower()
    ds_l = (source_dataset or "").lower()
    if "revenue" in name_l or "order_value" in col_l or "order_amount" in col_l or "revenue" in col_l:
        return {"kpi": "Revenue reporting", "description": "Revenue-related asset"}
    if "customer" in name_l or "customer" in col_l or "customer" in ds_l:
        return {"kpi": "Customer segmentation", "description": "Customer 360 view"}
    if "margin" in name_l or "discount" in col_l or "price" in col_l:
        return {"kpi": "Margin analysis", "description": "Margin/Promotion"}
    if "marketing" in name_l or "campaign" in col_l:
        return {"kpi": "Marketing attribution", "description": "Attribution, campaign ROI"}
    if "inventory" in name_l or "stock" in col_l:
        return {"kpi": "Inventory health", "description": "Stock levels"}
    return {"kpi": "Unknown", "description": "Generic asset"}

def _propagate_severity(source_severity: str, distance: int) -> str:
    """Distance decay: CRITICAL at 1 hop stays CRITICAL, at 2 -> WARNING, at 3+ -> INFO; WARNING at 2 -> INFO."""
    order = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
    rev = {0: "INFO", 1: "WARNING", 2: "CRITICAL"}
    src_rank = order.get(source_severity.upper(), 0)
    # Decay: -1 per hop beyond 1
    decay = max(0, distance - 1)
    new_rank = max(0, src_rank - decay)
    return rev[new_rank]

def analyze_impact(
    db: Session,
    dataset: str,
    column: Optional[str] = None,
    source_severity: str = "CRITICAL",
    max_depth: int = 3,
) -> Dict[str, Any]:
    """
    Deterministic impact analysis for a single column.
    Returns downstream assets with propagated severity, distance, KPI.
    """
    traversal = lineage_graph.traverse_graph(db, dataset, column, direction="downstream", max_depth=max_depth)
    impacted = []
    for edge in traversal["edges"]:
        distance = edge["depth"]
        propagated = _propagate_severity(source_severity, distance)
        target = edge["target_dataset"]
        kpi = _kpi_for_asset(target, column, dataset)
        impacted.append({
            "target_dataset": target,
            "target_column": edge.get("target_column"),
            "target_type": edge.get("target_type"),
            "job_name": edge.get("job_name"),
            "relationship": edge.get("relationship"),
            "distance": distance,
            "source_severity": source_severity,
            "propagated_severity": propagated,
            "kpi": kpi["kpi"],
            "kpi_description": kpi["description"],
            "evidence": f"{dataset}.{column or '*'} --{edge['relationship']}--> {target} (depth {distance})"
        })
    # Sort by severity (critical first) then distance
    severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    impacted.sort(key=lambda x: (severity_order.get(x["propagated_severity"], 3), x["distance"]))
    # Aggregate by KPI
    kpi_impact: Dict[str, Dict[str, Any]] = {}
    for imp in impacted:
        kpi = imp["kpi"]
        if kpi not in kpi_impact:
            kpi_impact[kpi] = {"kpi": kpi, "description": imp["kpi_description"], "assets": [], "max_severity": "INFO", "count": 0}
        kpi_impact[kpi]["assets"].append(imp["target_dataset"])
        kpi_impact[kpi]["count"] += 1
        # Max severity
        if severity_order.get(imp["propagated_severity"], 3) < severity_order.get(kpi_impact[kpi]["max_severity"], 3):
            kpi_impact[kpi]["max_severity"] = imp["propagated_severity"]
    # Also include direct source
    summary = f"Impact from {dataset}.{column or '*'} ({source_severity}) reaches {len(impacted)} downstream assets across {len(kpi_impact)} KPIs (depth {max_depth})"
    if not impacted:
        summary = f"No downstream impact for {dataset}.{column or '*'} — isolated or depth {max_depth} insufficient"
    return {
        "source": {"dataset": dataset, "column": column, "severity": source_severity},
        "max_depth": max_depth,
        "impacted_assets": impacted,
        "kpi_impact": list(kpi_impact.values()),
        "total_assets": len(impacted),
        "total_kpis": len(kpi_impact),
        "summary": summary,
    }

def analyze_scan_impact(db: Session, scan_id: int, max_depth: int = 3) -> Dict[str, Any]:
    """
    Impact for all issues in a scan: union of downstream for each affected column with its severity.
    """
    from models import Scan, Issue
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        raise ValueError(f"Scan {scan_id} not found")
    issues = db.query(Issue).filter(Issue.scan_id == scan_id).all()
    if not issues:
        return {
            "scan_id": scan_id,
            "dataset": scan.dataset.name if scan.dataset else "unknown",
            "source_columns": [],
            "summary": "No issues — no impact",
            "impacted_assets": [],
            "kpi_impact": [],
            "total_assets": 0,
            "total_kpis": 0,
        }
    # Collect per-column severity (max per column)
    col_severity: Dict[str, str] = {}
    for iss in issues:
        if not iss.column_name or " -> " in iss.column_name:
            continue
        col = iss.column_name
        sev = iss.severity
        # Keep max severity per column
        order = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
        if col not in col_severity or order.get(sev, 0) > order.get(col_severity[col], 0):
            col_severity[col] = sev
    # If no column-specific, use scan incident_severity
    if not col_severity:
        # Table-level impact: use scan severity
        col_severity["_table"] = scan.incident_severity or "INFO"

    # Union downstream
    all_impacted: Dict[str, Dict[str, Any]] = {}  # key target_dataset -> entry with max severity and min distance
    all_kpi: Dict[str, Dict[str, Any]] = {}
    for col, sev in col_severity.items():
        col_param = None if col == "_table" else col
        try:
            result = analyze_impact(db, scan.dataset.name, col_param, source_severity=sev, max_depth=max_depth)
            for imp in result["impacted_assets"]:
                key = imp["target_dataset"] + (f".{imp['target_column']}" if imp["target_column"] else "")
                # Keep max severity, min distance
                if key not in all_impacted:
                    all_impacted[key] = imp
                else:
                    # Keep more severe and closer
                    order = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
                    if order.get(imp["propagated_severity"], 0) > order.get(all_impacted[key]["propagated_severity"], 0):
                        all_impacted[key] = imp
                    elif imp["distance"] < all_impacted[key]["distance"]:
                        all_impacted[key] = imp
            for kpi_entry in result["kpi_impact"]:
                kpi = kpi_entry["kpi"]
                if kpi not in all_kpi:
                    all_kpi[kpi] = kpi_entry
                else:
                    # Merge assets
                    for a in kpi_entry["assets"]:
                        if a not in all_kpi[kpi]["assets"]:
                            all_kpi[kpi]["assets"].append(a)
                    # Max severity
                    order = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
                    if order.get(kpi_entry["max_severity"], 0) > order.get(all_kpi[kpi]["max_severity"], 0):
                        all_kpi[kpi]["max_severity"] = kpi_entry["max_severity"]
        except Exception:
            continue

    impacted_list = sorted(all_impacted.values(), key=lambda x: ({"CRITICAL": 0, "WARNING": 1, "INFO": 2}.get(x["propagated_severity"], 3), x["distance"]))
    kpi_list = sorted(all_kpi.values(), key=lambda x: {"CRITICAL": 0, "WARNING": 1, "INFO": 2}.get(x["max_severity"], 3))
    summary = f"Scan {scan_id} impact: {len(impacted_list)} downstream assets, {len(kpi_list)} KPIs affected (from {len(col_severity)} source columns)"
    if not impacted_list:
        summary = f"Scan {scan_id} — no downstream lineage, no business impact"
    return {
        "scan_id": scan_id,
        "dataset": scan.dataset.name if scan.dataset else "unknown",
        "source_columns": list(col_severity.keys()),
        "impacted_assets": impacted_list,
        "kpi_impact": kpi_list,
        "total_assets": len(impacted_list),
        "total_kpis": len(kpi_list),
        "summary": summary,
    }
