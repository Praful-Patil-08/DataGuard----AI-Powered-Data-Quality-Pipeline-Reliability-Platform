"""
Historical Reliability — Elementary-inspired observability.

Provides deterministic analytics over historical scans/issues/incidents:
- quality_score trend (avg per day)
- issue count trends (critical/warning)
- most problematic datasets (by avg quality_score, incident count)
- most problematic columns (by issue frequency)
- incident frequency per day
- quality degradation detection (recent vs historical avg)

All computed on-the-fly from Scan/Issue/Incident tables (no new storage).
Study: Elementary historical metrics, anomaly detection, reliability trends.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
import models

def _date_str(dt: Optional[datetime]) -> str:
    if not dt:
        return datetime.now(timezone.utc).date().isoformat()
    return dt.date().isoformat()

def get_reliability_trends(
    db: Session,
    dataset_id: Optional[int] = None,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """
    Returns per-day buckets with avg quality_score, issue counts, incident counts.
    If dataset_id provided, filters to that dataset (and its logical prefix?).
    """
    now = datetime.now(timezone.utc)
    # Determine dataset filter: if dataset_id provided, use logical prefix like other history endpoints
    dataset_ids: Optional[List[int]] = None
    if dataset_id:
        ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
        if ds:
            # Find logical prefix datasets
            prefix = ds.name.split("_")[0] if ds.name else ds.name
            related = db.query(models.Dataset).filter(models.Dataset.name.like(f"{prefix}%")).all()
            dataset_ids = [d.id for d in related] if related else [dataset_id]
        else:
            dataset_ids = [dataset_id]
    # Query scans
    q = db.query(models.Scan)
    if dataset_ids:
        q = q.filter(models.Scan.dataset_id.in_(dataset_ids))
    scans = q.order_by(models.Scan.completed_at.asc()).all()
    # Bucket by date
    buckets: Dict[str, Dict[str, Any]] = {}
    for s in scans:
        d = _date_str(s.completed_at)
        if d not in buckets:
            buckets[d] = {"date": d, "scans": 0, "quality_scores": [], "critical": 0, "warning": 0, "healthy": 0, "incidents": 0}
        buckets[d]["scans"] += 1
        if s.quality_score is not None:
            buckets[d]["quality_scores"].append(float(s.quality_score))
        if s.critical_count and s.critical_count > 0:
            buckets[d]["critical"] += 1
        elif s.warning_count and s.warning_count > 0:
            buckets[d]["warning"] += 1
        else:
            buckets[d]["healthy"] += 1
    # Also count incidents per day (from Incident table)
    inc_q = db.query(models.Incident)
    if dataset_ids:
        inc_q = inc_q.filter(models.Incident.dataset_id.in_(dataset_ids))
    incidents = inc_q.all()
    for inc in incidents:
        d = _date_str(inc.created_at)
        if d not in buckets:
            buckets[d] = {"date": d, "scans": 0, "quality_scores": [], "critical": 0, "warning": 0, "healthy": 0, "incidents": 0}
        # Ensure key exists
        if "incidents" not in buckets[d]:
            buckets[d]["incidents"] = 0
        buckets[d]["incidents"] += 1
    # Build trend for last `days` days
    trend = []
    for i in range(days):
        day = (now.date() - timedelta(days=days-1-i)).isoformat()
        b = buckets.get(day, {"date": day, "scans": 0, "quality_scores": [], "critical": 0, "warning": 0, "healthy": 0, "incidents": 0})
        avg_score = round(sum(b["quality_scores"]) / len(b["quality_scores"]), 1) if b["quality_scores"] else None
        total_issues = b["critical"] + b["warning"]
        trend.append({
            "date": day,
            "scans": b["scans"],
            "avg_quality_score": avg_score,
            "critical_scans": b["critical"],
            "warning_scans": b["warning"],
            "healthy_scans": b["healthy"],
            "incidents": b.get("incidents", 0),
            "total_issues": total_issues,
        })
    return trend

def get_most_problematic_datasets(
    db: Session,
    limit: int = 5,
    days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Ranks datasets by reliability: lowest avg quality_score, highest incident count.
    If days provided, only considers recent scans.
    """
    # Get all datasets
    datasets = db.query(models.Dataset).all()
    rankings = []
    cutoff = None
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for ds in datasets:
        q = db.query(models.Scan).filter(models.Scan.dataset_id == ds.id)
        if cutoff:
            q = q.filter(models.Scan.completed_at >= cutoff)
        scans = q.all()
        if not scans:
            continue
        scores = [float(s.quality_score) for s in scans if s.quality_score is not None]
        avg_score = round(sum(scores)/len(scores), 1) if scores else None
        total_critical = sum(s.critical_count or 0 for s in scans)
        total_warning = sum(s.warning_count or 0 for s in scans)
        total_incidents = db.query(models.Incident).filter(models.Incident.dataset_id == ds.id).count()
        # Problematic if low score or high incidents
        # Compute problem_score: lower avg_score + higher incidents => more problematic
        # We sort by avg_score ascending, then incidents descending
        rankings.append({
            "dataset_id": ds.id,
            "dataset_name": ds.name,
            "filename": ds.filename,
            "scan_count": len(scans),
            "avg_quality_score": avg_score,
            "total_critical": total_critical,
            "total_warning": total_warning,
            "total_incidents": total_incidents,
            "last_scan_at": max(s.completed_at for s in scans).isoformat() if scans else None,
        })
    # Sort: lowest avg_score first, then highest incidents
    rankings.sort(key=lambda x: ((x["avg_quality_score"] if x["avg_quality_score"] is not None else 100), -x["total_incidents"]))
    return rankings[:limit]

def get_most_problematic_columns(
    db: Session,
    limit: int = 10,
    days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Ranks columns by issue frequency (how often they appear in issues).
    """
    cutoff = None
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    # Query issues joined with scans to get dataset
    q = db.query(models.Issue, models.Scan).join(models.Scan, models.Issue.scan_id == models.Scan.id)
    if cutoff:
        q = q.filter(models.Scan.completed_at >= cutoff)
    rows = q.all()
    col_stats: Dict[str, Dict[str, Any]] = {}
    for issue, scan in rows:
        if not issue.column_name or " -> " in issue.column_name:
            # For rename, count both parts
            if issue.column_name and " -> " in issue.column_name:
                for part in issue.column_name.split(" -> "):
                    key = f"{scan.dataset.name}.{part}" if scan.dataset else part
                    if key not in col_stats:
                        col_stats[key] = {"column": part, "dataset": scan.dataset.name if scan.dataset else "unknown", "count": 0, "critical": 0, "warning": 0, "types": set()}
                    col_stats[key]["count"] += 1
                    if issue.severity == "CRITICAL":
                        col_stats[key]["critical"] += 1
                    elif issue.severity == "WARNING":
                        col_stats[key]["warning"] += 1
                    col_stats[key]["types"].add(issue.issue_type)
                continue
            else:
                continue
        else:
            key = f"{scan.dataset.name}.{issue.column_name}" if scan.dataset else issue.column_name
            if key not in col_stats:
                col_stats[key] = {"column": issue.column_name, "dataset": scan.dataset.name if scan.dataset else "unknown", "full_key": key, "count": 0, "critical": 0, "warning": 0, "types": set()}
            col_stats[key]["count"] += 1
            if issue.severity == "CRITICAL":
                col_stats[key]["critical"] += 1
            elif issue.severity == "WARNING":
                col_stats[key]["warning"] += 1
            col_stats[key]["types"].add(issue.issue_type)
    # Convert to list
    result = []
    for key, v in col_stats.items():
        result.append({
            "column": v["column"],
            "dataset": v["dataset"],
            "full_key": key,
            "issue_count": v["count"],
            "critical_count": v["critical"],
            "warning_count": v["warning"],
            "distinct_issue_types": sorted(list(v["types"])),
        })
    result.sort(key=lambda x: (-x["issue_count"], -x["critical_count"], x["column"]))
    return result[:limit]

def get_incident_frequency(
    db: Session,
    days: int = 30,
    dataset_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Incident frequency per day."""
    now = datetime.now(timezone.utc)
    q = db.query(models.Incident)
    if dataset_id:
        ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
        if ds:
            prefix = ds.name.split("_")[0] if ds.name else ds.name
            related = db.query(models.Dataset).filter(models.Dataset.name.like(f"{prefix}%")).all()
            ids = [d.id for d in related] if related else [dataset_id]
            q = q.filter(models.Incident.dataset_id.in_(ids))
        else:
            q = q.filter(models.Incident.dataset_id == dataset_id)
    incidents = q.all()
    buckets: Dict[str, int] = {}
    for inc in incidents:
        d = _date_str(inc.created_at)
        buckets[d] = buckets.get(d, 0) + 1
    trend = []
    for i in range(days):
        day = (now.date() - timedelta(days=days-1-i)).isoformat()
        trend.append({"date": day, "incidents": buckets.get(day, 0)})
    return trend

def detect_quality_degradation(
    db: Session,
    dataset_id: Optional[int] = None,
    window: int = 5,
) -> Dict[str, Any]:
    """
    Detects quality degradation: recent avg quality_score vs historical avg.
    Returns evidence with baseline, current, delta, threshold.
    """
    q = db.query(models.Scan).order_by(models.Scan.completed_at.desc())
    if dataset_id:
        ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
        if ds:
            prefix = ds.name.split("_")[0] if ds.name else ds.name
            related = db.query(models.Dataset).filter(models.Dataset.name.like(f"{prefix}%")).all()
            ids = [d.id for d in related] if related else [dataset_id]
            q = q.filter(models.Scan.dataset_id.in_(ids))
        else:
            q = q.filter(models.Scan.dataset_id == dataset_id)
    scans = q.limit(window*2).all()
    # Need at least window*2 scans to compare recent vs historical? For MVP, compare last `window` vs previous `window`
    if len(scans) < window:
        return {
            "status": "insufficient_data",
            "message": f"Need at least {window} scans, have {len(scans)}",
            "scans_considered": len(scans),
        }
    # Most recent `window` are first `window` in desc order
    recent = scans[:window]
    historical = scans[window:window*2] if len(scans) >= window*2 else scans[window:]
    if not historical:
        historical = scans[window:]
        if not historical:
            return {"status": "insufficient_data", "message": "Not enough historical scans"}
    recent_scores = [float(s.quality_score) for s in recent if s.quality_score is not None]
    hist_scores = [float(s.quality_score) for s in historical if s.quality_score is not None]
    if not recent_scores or not hist_scores:
        return {"status": "insufficient_data", "message": "No quality scores"}
    recent_avg = sum(recent_scores)/len(recent_scores)
    hist_avg = sum(hist_scores)/len(hist_scores)
    delta = round(recent_avg - hist_avg, 2)
    # Threshold: degradation if recent avg < historical avg -5 points
    threshold = -5.0
    is_degraded = delta <= threshold
    # Also check trend: if recent scores are decreasing monotonic
    trend_decreasing = all(recent_scores[i] <= recent_scores[i+1] for i in range(len(recent_scores)-1)) if len(recent_scores) > 1 else False
    return {
        "status": "degraded" if is_degraded else "stable",
        "recent_avg": round(recent_avg, 2),
        "historical_avg": round(hist_avg, 2),
        "delta": delta,
        "threshold": threshold,
        "window": window,
        "recent_scores": [round(s,1) for s in recent_scores],
        "historical_scores": [round(s,1) for s in hist_scores],
        "trend_decreasing": trend_decreasing,
        "evidence": f"Recent {window} avg {recent_avg:.1f} vs historical {hist_avg:.1f} delta {delta:+.1f} (threshold {threshold})",
    }

def get_reliability_overview(db: Session) -> Dict[str, Any]:
    """Overall reliability overview for dashboard."""
    total_scans = db.query(models.Scan).count()
    total_incidents = db.query(models.Incident).count()
    total_datasets = db.query(models.Dataset).count()
    # Avg quality score across all scans
    avg_score = db.query(func.avg(models.Scan.quality_score)).scalar()
    avg_score = round(float(avg_score), 1) if avg_score is not None else None
    # Recent degradation
    degradation = detect_quality_degradation(db, window=5)
    # Most problematic
    problematic_datasets = get_most_problematic_datasets(db, limit=3)
    problematic_columns = get_most_problematic_columns(db, limit=3)
    # Incident frequency last 7 days
    incident_trend = get_incident_frequency(db, days=7)
    recent_incidents = sum(d["incidents"] for d in incident_trend)
    return {
        "total_scans": total_scans,
        "total_incidents": total_incidents,
        "total_datasets": total_datasets,
        "avg_quality_score": avg_score,
        "degradation": degradation,
        "most_problematic_datasets": problematic_datasets,
        "most_problematic_columns": problematic_columns,
        "recent_incidents_7d": recent_incidents,
        "incident_trend_7d": incident_trend,
    }
