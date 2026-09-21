"""
Incident Correlation — deterministic grouping of related issues.

Study:
- Elementary: incident concepts, historical metrics, trend analysis — groups related findings by dataset and time
- No LLM for basic correlation: we use deterministic evidence (same scan, same dataset, column overlap, issue_type families, lineage overlap)

Design for MVP:
- One incident per scan (all issues in scan are considered correlated via same ingestion/run)
- Grouping evidence includes:
  * shared_scan: all issues share same scan_id
  * affected_columns: union of issue column_names
  * families: which issue_type families are present (schema, drift, statistical, quality, contract)
  * column_overlap: which columns appear in multiple issues (e.g., customer_id appears in null drift + completeness breach)
  * downstream_overlap: which downstream assets are affected by multiple issues (via lineage)
- Title generation deterministic: based on most severe family and incident_summary
- Severity = scan.incident_severity or max(issue severity)
- Never uses LLM
"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc
import models
from lineage import get_downstream_impact

# Families for deterministic grouping
FAMILY_MAP: Dict[str, str] = {
    # schema
    "COLUMN_REMOVED": "schema",
    "COLUMN_ADDED": "schema",
    "TYPE_CHANGED": "schema",
    "NULLABILITY_CHANGED": "schema",
    "COLUMN_RENAMED_CANDIDATE": "schema",
    # drift
    "NULL_RATE_DRIFT": "drift",
    "CARDINALITY_DRIFT": "drift",
    "NUMERIC_DRIFT": "drift",
    "ROW_COUNT_DRIFT": "drift",
    # statistical
    "NUMERIC_PSI_DRIFT": "statistical",
    "NUMERIC_KS_DRIFT": "statistical",
    "CATEGORICAL_PSI_DRIFT": "statistical",
    "CATEGORICAL_JSD_DRIFT": "statistical",
    # quality
    "EMPTY_DATASET": "quality",
    "PRIMARY_KEY_NULL": "quality",
    "DUPLICATE_PRIMARY_KEY": "quality",
    "DUPLICATE_ROWS": "quality",
    "HIGH_NULL_RATE": "quality",
    "NEGATIVE_VALUE_ANOMALY": "quality",
    "NUMERIC_ANOMALY": "quality",
    "MALFORMED_DATE": "quality",
    "CATEGORICAL_INCONSISTENCY": "quality",
    "RULE_EXECUTION_ERROR": "quality",
    # contract
    "CONTRACT_BREACH_COMPLETENESS": "contract",
    "CONTRACT_BREACH_UNIQUENESS": "contract",
    "CONTRACT_BREACH_RANGE": "contract",
    "CONTRACT_BREACH_REGEX": "contract",
    "CONTRACT_BREACH_ROW_COUNT": "contract",
    "CONTRACT_UNKNOWN_TYPE": "contract",
    "CONTRACT_EVALUATION_ERROR": "contract",
}

def _family(issue_type: str) -> str:
    return FAMILY_MAP.get(issue_type, "other")

def _severity_rank(sev: str) -> int:
    return {"INFO": 0, "WARNING": 1, "CRITICAL": 2}.get(sev.upper(), 0)

def generate_incident_title(scan: models.Scan, issues: List[models.Issue], families: List[str]) -> str:
    """Deterministic title based on scan summary and families."""
    # Use scan.incident_summary first 80 chars if available
    base = scan.incident_summary or ""
    # If no summary, derive from families
    if not base:
        if not issues:
            return f"Healthy scan for {scan.dataset.name if scan.dataset else 'dataset'} — no issues"
        # Use most severe issue's column
        # Find critical issue
        crits = [i for i in issues if i.severity == "CRITICAL"]
        if crits:
            col = crits[0].column_name or crits[0].issue_type
            return f"{scan.dataset.name if scan.dataset else 'Dataset'} degraded: {col} critical ({crits[0].issue_type})"
        warns = [i for i in issues if i.severity == "WARNING"]
        if warns:
            return f"{scan.dataset.name if scan.dataset else 'Dataset'} drift: {warns[0].issue_type} warning"
        return f"Incident for {scan.dataset.name if scan.dataset else 'dataset'}: {len(issues)} issues"
    # Shorten if too long
    if len(base) > 120:
        base = base[:117] + "..."
    # Add family hint if multiple families
    if len(families) > 1:
        return base
    # If single family, add it
    if families:
        family = families[0]
        if family not in base.lower():
            return f"{base} ({family})"
    return base

def generate_root_cause(scan: models.Scan, issues: List[models.Issue], families: List[str], affected_columns: List[str]) -> str:
    """Deterministic root cause hypothesis without LLM."""
    if not issues:
        return "No issues — data adheres to baseline and contracts."
    # Check families present
    has_schema = "schema" in families
    has_drift = "drift" in families
    has_stat = "statistical" in families
    has_quality = "quality" in families
    has_contract = "contract" in families

    parts = []
    if has_schema:
        removed = [i for i in issues if i.issue_type == "COLUMN_REMOVED"]
        if removed:
            parts.append(f"Schema change: columns removed {', '.join(i.column_name for i in removed)}")
        type_changed = [i for i in issues if i.issue_type == "TYPE_CHANGED"]
        if type_changed:
            parts.append(f"Type regression: {', '.join(i.column_name for i in type_changed)}")
        # Rename candidate
        renames = [i for i in issues if i.issue_type == "COLUMN_RENAMED_CANDIDATE"]
        if renames:
            r = renames[0]
            parts.append(f"Possible rename {r.column_name} (confidence {r.issue_metadata.get('confidence')})")
    if has_drift or has_stat:
        # Find worst drift
        drifts = [i for i in issues if FAMILY_MAP.get(i.issue_type) in ("drift", "statistical")]
        if drifts:
            # Group by column
            by_col: Dict[str, List[models.Issue]] = {}
            for d in drifts:
                by_col.setdefault(d.column_name or "table", []).append(d)
            for col, ds in by_col.items():
                parts.append(f"Distribution drift on {col}: {', '.join(d.issue_type for d in ds)}")
    if has_quality:
        # Find quality on which columns
        quals = [i for i in issues if FAMILY_MAP.get(i.issue_type) == "quality"]
        if quals:
            # Dedupe column
            cols = sorted(set(i.column_name for i in quals if i.column_name))
            if cols:
                parts.append(f"Quality breach on {', '.join(cols[:3])}: {', '.join(set(i.issue_type for i in quals))}")
            else:
                parts.append(f"Quality breach: {', '.join(set(i.issue_type for i in quals))}")
    if has_contract:
        contracts = [i for i in issues if FAMILY_MAP.get(i.issue_type) == "contract"]
        if contracts:
            cols = sorted(set(i.column_name for i in contracts if i.column_name))
            parts.append(f"Contract violation on {', '.join(cols[:3]) if cols else 'table'}")
    if not parts:
        # Fallback: list issue types
        types = sorted(set(i.issue_type for i in issues))
        parts.append(f"Issues: {', '.join(types[:3])}")
    # Join with deterministic logic: if multiple families, suggest upstream pipeline change
    if len(families) > 1:
        parts.append("Suggest checking upstream ingestion/deployment in last 24h (multiple families indicate pipeline change).")
    return " ".join(parts)

def correlate_incidents_for_scan(db: Session, scan: models.Scan, issues: List[models.Issue]) -> models.Incident:
    """
    Create one incident per scan deterministically.
    Returns the created Incident.
    """
    # Collect families
    families = sorted(set(_family(i.issue_type) for i in issues))
    # Affected columns
    affected_columns = sorted(set(i.column_name for i in issues if i.column_name and " -> " not in i.column_name))
    # For rename candidates, split
    for i in issues:
        if i.issue_type == "COLUMN_RENAMED_CANDIDATE" and i.column_name and " -> " in i.column_name:
            parts = i.column_name.split(" -> ")
            for p in parts:
                if p not in affected_columns:
                    affected_columns.append(p)
    affected_columns = sorted(set(affected_columns))
    # Downstream assets via lineage
    affected_assets = []
    try:
        for col in affected_columns:
            impacts = get_downstream_impact(scan.dataset.name if scan.dataset else "unknown", col)
            for imp in impacts:
                if imp["name"] not in affected_assets:
                    affected_assets.append(imp["name"])
    except Exception:
        pass
    # Severity: max of scan incident_severity and issue severities
    max_issue_sev = max([i.severity for i in issues], key=_severity_rank) if issues else "INFO"
    # Use scan incident_severity as primary, but if max_issue_sev higher, use that
    scan_sev = scan.incident_severity or "INFO"
    # Determine final severity: highest rank
    severities = ["INFO", "WARNING", "CRITICAL"]
    # Map to rank
    rank_scan = _severity_rank(scan_sev)
    rank_issue = _severity_rank(max_issue_sev)
    final_sev = severities[max(rank_scan, rank_issue)]
    if not issues:
        final_sev = "INFO"

    title = generate_incident_title(scan, issues, families)
    root_cause = generate_root_cause(scan, issues, families, affected_columns)

    # Correlation evidence
    # Column overlap: columns appearing in multiple issues
    col_counts: Dict[str, int] = {}
    for i in issues:
        if i.column_name:
            # For rename, count both parts
            if " -> " in i.column_name:
                for p in i.column_name.split(" -> "):
                    col_counts[p] = col_counts.get(p, 0) + 1
            else:
                col_counts[i.column_name] = col_counts.get(i.column_name, 0) + 1
    overlapping_columns = [col for col, cnt in col_counts.items() if cnt > 1]

    # Family overlap
    family_counts: Dict[str, int] = {}
    for i in issues:
        fam = _family(i.issue_type)
        family_counts[fam] = family_counts.get(fam, 0) + 1

    # Downstream overlap: assets appearing from multiple columns
    # Already collected, but check if any asset appears via multiple columns
    # For MVP, we just note that assets exist

    correlation_evidence = {
        "families": families,
        "family_counts": family_counts,
        "affected_columns": affected_columns,
        "overlapping_columns": overlapping_columns,
        "downstream_assets": affected_assets[:5],
        "issue_count": len(issues),
        "scan_incident_summary": scan.incident_summary,
        "scan_quality_score": float(scan.quality_score) if scan.quality_score is not None else None,
    }

    # Determine status: OPEN if critical/warning, RESOLVED if healthy/info
    if final_sev in ("CRITICAL", "WARNING"):
        status = "OPEN"
    else:
        status = "RESOLVED" if not issues else "OPEN"

    incident = models.Incident(
        scan_id=scan.id,
        dataset_id=scan.dataset_id,
        dataset_name=scan.dataset.name if scan.dataset else "unknown",
        title=title[:255],
        severity=final_sev,
        status=status,
        root_cause=root_cause,
        affected_columns=affected_columns,
        affected_assets=affected_assets,
        issue_ids=[i.id for i in issues],
        issue_types=sorted(set(i.issue_type for i in issues)),
        issue_count=len(issues),
        correlation_evidence=correlation_evidence,
        quality_score_at_incident=float(scan.quality_score) if scan.quality_score is not None else None,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident

def list_incidents(
    db: Session,
    dataset_id: Optional[int] = None,
    dataset_name: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[models.Incident]:
    q = db.query(models.Incident).order_by(desc(models.Incident.created_at))
    if dataset_id:
        q = q.filter(models.Incident.dataset_id == dataset_id)
    if dataset_name:
        # prefix match like other managers
        all_inc = q.all()
        matched = [i for i in all_inc if i.dataset_name.lower() == dataset_name.lower() or i.dataset_name.lower().startswith(dataset_name.lower().split("_")[0])]
        if severity:
            matched = [i for i in matched if i.severity == severity.upper()]
        if status:
            matched = [i for i in matched if i.status == status.upper()]
        return matched[:limit]
    if severity:
        q = q.filter(models.Incident.severity == severity.upper())
    if status:
        q = q.filter(models.Incident.status == status.upper())
    return q.limit(limit).all()
