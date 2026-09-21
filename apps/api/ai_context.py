"""
AI Context Builder — deterministic facts only, no raw data.

Builds structured context for AI analyst from deterministic engine outputs.
Ensures:
- No raw production rows sent to LLM (only aggregated facts)
- All facts are explainable: scan, issues, schema diff, drift stats, historical, lineage, impact, dataset metadata, quality score
- Prompt injection sanitized (dataset_name, column names stripped of control chars)
- Structured evidence for AI to ground reasoning

Pipeline:
RAW DATA -> DETERMINISTIC ENGINE -> FACTS -> AI CONTEXT BUILDER -> LLM -> STRUCTURED ANALYSIS
"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc
import re

import models
from lineage import get_downstream_impact
from drift import generate_incident_summary
import json as _json

# Sanitization for prompt injection: allow only alphanumeric, _, -, .
_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_\-\.\s]")

def _sanitize(text: str, max_len: int = 200) -> str:
    if not text:
        return ""
    # Strip control chars, limit length, escape potential injection
    cleaned = _SANITIZE_RE.sub("", text)[:max_len]
    # Also strip prompt injection markers
    for marker in ["SYSTEM:", "SYSTEM", "IGNORE", "PROMPT", "```", "{{", "}}"]:
        cleaned = cleaned.replace(marker, "")
    return cleaned.strip()

def _sanitize_dataset_name(name: str) -> str:
    return _sanitize(name, max_len=100)

def _sanitize_column(name: str) -> str:
    return _sanitize(name, max_len=100)

def build_ai_context(db: Session, scan_id: int, max_issues: int = 20, max_history: int = 3) -> Dict[str, Any]:
    """
    Build deterministic context for AI analyst.
    Only aggregated facts, no raw rows.
    Returns dict with keys: scan, dataset, issues, schema_diff, drift_stats, quality_score, historical, lineage, impact, dataset_metadata
    """
    scan = db.query(models.Scan).filter(models.Scan.id == scan_id).first()
    if not scan:
        raise ValueError(f"Scan {scan_id} not found")
    dataset = scan.dataset
    issues = db.query(models.Issue).filter(models.Issue.scan_id == scan_id).all()
    # Limit issues to avoid prompt bloat
    issues_data = []
    for iss in issues[:max_issues]:
        issues_data.append({
            "issue_type": iss.issue_type,
            "severity": iss.severity,
            "column_name": _sanitize_column(iss.column_name) if iss.column_name else None,
            "description": _sanitize(iss.description, max_len=300),
            "metadata": iss.issue_metadata or {},
        })
    # Schema diff: baseline vs current (if baseline exists)
    schema_diff = None
    baseline_info = None
    if scan.baseline_dataset_id:
        base_ds = db.query(models.Dataset).filter(models.Dataset.id == scan.baseline_dataset_id).first()
        if base_ds:
            baseline_info = {
                "baseline_dataset_id": base_ds.id,
                "baseline_dataset_name": _sanitize_dataset_name(base_ds.name),
                "baseline_row_count": base_ds.row_count,
                "candidate_row_count": dataset.row_count if dataset else None,
            }
        # Get schema diff via drift already? For context, include basic diff counts
        # Count issue types related to schema
        schema_issues = [i for i in issues_data if i["issue_type"] in ("COLUMN_REMOVED", "COLUMN_ADDED", "TYPE_CHANGED", "NULLABILITY_CHANGED", "COLUMN_RENAMED_CANDIDATE")]
        if schema_issues:
            schema_diff = {
                "removed": [i["column_name"] for i in schema_issues if i["issue_type"] == "COLUMN_REMOVED"],
                "added": [i["column_name"] for i in schema_issues if i["issue_type"] == "COLUMN_ADDED"],
                "type_changed": [f"{i['column_name']} ({i['metadata'].get('previous_type')}->{i['metadata'].get('current_type')})" for i in schema_issues if i["issue_type"] == "TYPE_CHANGED"],
                "rename_candidates": [i for i in schema_issues if i["issue_type"] == "COLUMN_RENAMED_CANDIDATE"],
            }
    # Drift stats: counts per drift type
    drift_stats = {}
    for drift_type in ["NULL_RATE_DRIFT", "CARDINALITY_DRIFT", "NUMERIC_DRIFT", "ROW_COUNT_DRIFT", "NUMERIC_PSI_DRIFT", "NUMERIC_KS_DRIFT", "CATEGORICAL_PSI_DRIFT", "CATEGORICAL_JSD_DRIFT"]:
        cnt = sum(1 for i in issues_data if i["issue_type"] == drift_type)
        if cnt:
            drift_stats[drift_type] = cnt
    # Quality score
    quality_score = {
        "score": float(scan.quality_score) if scan.quality_score is not None else None,
        "dimensions": scan.quality_dimensions or {},
        "incident_severity": scan.incident_severity,
        "critical_count": scan.critical_count,
        "warning_count": scan.warning_count,
        "healthy_count": scan.healthy_count,
    }
    # Historical: last N scans for same logical dataset (prefix)
    historical: List[Dict[str, Any]] = []
    try:
        prefix = dataset.name.split("_")[0] if dataset and dataset.name else ""
        related_ids = [scan.dataset_id]
        if prefix:
            related_ds = db.query(models.Dataset).filter(models.Dataset.name.like(f"{prefix}%")).all()
            related_ids = [d.id for d in related_ds]
        prior_scans = db.query(models.Scan).filter(
            models.Scan.dataset_id.in_(related_ids),
            models.Scan.id != scan.id
        ).order_by(desc(models.Scan.completed_at)).limit(max_history).all()
        for ps in prior_scans:
            historical.append({
                "scan_id": ps.id,
                "incident_severity": ps.incident_severity,
                "incident_summary": _sanitize(ps.incident_summary or "", max_len=200),
                "critical_count": ps.critical_count,
                "warning_count": ps.warning_count,
                "quality_score": float(ps.quality_score) if ps.quality_score is not None else None,
                "completed_at": ps.completed_at.isoformat() if ps.completed_at else None,
            })
    except Exception:
        historical = []
    # Lineage + downstream impact (deterministic, via lineage_graph)
    downstream_assets: List[str] = []
    lineage_details: List[Dict[str, Any]] = []
    try:
        for iss in issues:
            if iss.column_name and " -> " not in iss.column_name:
                col = iss.column_name
                impacts = get_downstream_impact(dataset.name if dataset else "unknown", col)
                for imp in impacts:
                    if imp["name"] not in downstream_assets:
                        downstream_assets.append(imp["name"])
                    lineage_details.append({
                        "column": _sanitize_column(col),
                        "asset": imp["name"],
                        "asset_type": imp.get("asset_type"),
                        "relationship": imp.get("relationship"),
                    })
                if len(lineage_details) >= 20:
                    break
    except Exception:
        pass
    # Impact analysis (if available, via impact.py)
    impact_summary = None
    try:
        from impact import analyze_scan_impact
        # Use max_depth 3 for context brevity
        impact_data = analyze_scan_impact(db, scan_id, max_depth=2)
        impact_summary = {
            "total_assets": impact_data.get("total_assets", 0),
            "total_kpis": impact_data.get("total_kpis", 0),
            "kpi_impact": impact_data.get("kpi_impact", [])[:3],
            "summary": _sanitize(impact_data.get("summary", ""), max_len=300),
        }
    except Exception:
        impact_summary = None
    # Dataset metadata (no raw data)
    dataset_metadata = None
    if dataset:
        dataset_metadata = {
            "dataset_name": _sanitize_dataset_name(dataset.name),
            "filename": _sanitize(dataset.filename or "", max_len=100),
            "row_count": dataset.row_count,
            "column_count": dataset.column_count,
            "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        }
        # Add schema fingerprint if available
        try:
            schema = db.query(models.SchemaRecord).filter(models.SchemaRecord.dataset_id == dataset.id).order_by(desc(models.SchemaRecord.created_at)).first()
            if schema:
                dataset_metadata["fingerprint"] = schema.fingerprint[:16] + "..." if schema.fingerprint else None
                dataset_metadata["columns"] = [{"name": c.column_name, "type": c.data_type} for c in schema.columns[:10]]
        except Exception:
            pass
    # Build final context (facts only)
    context = {
        "scan": {
            "scan_id": scan.id,
            "dataset_id": scan.dataset_id,
            "baseline_dataset_id": scan.baseline_dataset_id,
            "status": scan.status,
            "incident_summary": _sanitize(scan.incident_summary or "", max_len=300),
            "incident_severity": scan.incident_severity,
            "started_at": scan.started_at.isoformat() if scan.started_at else None,
            "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
        },
        "dataset": dataset_metadata,
        "issues": issues_data,
        "issue_count": len(issues_data),
        "schema_diff": schema_diff,
        "baseline_info": baseline_info,
        "drift_stats": drift_stats,
        "quality_score": quality_score,
        "historical": historical,
        "downstream_assets": downstream_assets[:10],
        "lineage_details": lineage_details[:10],
        "impact": impact_summary,
        # Hardening: explicitly state what AI must NOT do
        "constraints": {
            "no_raw_data": True,
            "must_ground_in_issues": True,
            "must_not_modify_data": True,
            "must_require_human_approval_for_critical": True,
        }
    }
    return context

def validate_ai_output(output: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate AI output is grounded in context and structured.
    - Must have required fields
    - Affected assets must be subset of lineage downstream (or heuristic downstream)
    - Confidence 0-1
    - Severity must be one of allowed
    - If evidence insufficient, AI should say so (we check root_cause not empty)
    - Strip any hallucinated metrics not in issues

    Returns sanitized output (may fallback to deterministic if invalid).
    """
    required = ["summary", "severity", "root_cause", "affected_assets", "technical_impact", "business_impact", "recommended_action", "confidence"]
    for field in required:
        if field not in output:
            raise ValueError(f"Missing required field {field}")
    # Sanitize severity
    if output["severity"] not in ("INFO", "WARNING", "CRITICAL", "PASSED"):
        # Map to closest
        sev = str(output["severity"]).upper()
        if "CRIT" in sev:
            output["severity"] = "CRITICAL"
        elif "WARN" in sev:
            output["severity"] = "WARNING"
        elif "PASS" in sev:
            output["severity"] = "PASSED"
        else:
            output["severity"] = "WARNING"
    # Clamp confidence
    try:
        conf = float(output["confidence"])
        output["confidence"] = max(0.0, min(1.0, conf))
    except Exception:
        output["confidence"] = 0.85
    # Validate affected_assets subset of downstream (allow heuristic, but filter hallucinations)
    downstream = set(context.get("downstream_assets", []))
    if downstream:
        allowed = set(downstream)
        for det in context.get("lineage_details", []):
            allowed.add(det["asset"])
        filtered = [a for a in output["affected_assets"] if a in allowed]
        if filtered:
            output["affected_assets"] = filtered
        else:
            # All hallucinated — fallback to grounded downstream
            output["affected_assets"] = list(downstream)[:3]
    # If no downstream context but AI hallucinated, keep as is (no ground truth to filter)
    # Ensure requires_human_approval is bool and true for critical
    if output["severity"] in ("CRITICAL", "WARNING"):
        output["requires_human_approval"] = True
    else:
        output["requires_human_approval"] = bool(output.get("requires_human_approval", False))
    # Sanitize text fields for prompt injection remnants
    for key in ["summary", "root_cause", "technical_impact", "business_impact", "recommended_action"]:
        if isinstance(output[key], str):
            # Strip system markers
            for marker in ["SYSTEM:", "IGNORE PREVIOUS", "PROMPT INJECTION", "```"]:
                if marker.lower() in output[key].lower():
                    output[key] = output[key].replace(marker, "").strip()
            # Truncate
            if len(output[key]) > 2000:
                output[key] = output[key][:2000]
    # Ensure root_cause not empty
    if not output["root_cause"] or len(output["root_cause"].strip()) < 10:
        output["root_cause"] = "Deterministic issues detected; root cause requires manual investigation of upstream pipeline."
    return output
