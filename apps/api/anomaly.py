"""
Anomaly Detection — statistical, not ML.

Uses historical observations to flag meaningful deviations.
Example: historical null rates [2.1,2.4,2.0,2.3,2.2] vs current 14.8 => anomaly.

Methods (chosen per spec — no fake ML):
- z-score: (current - mean) / std ; threshold |z| >= 3.0 (critical) / 2.0 (warning) for n>=5
- IQR fence: if n < 5 or std==0, use IQR (q1 -1.5*IQR, q3+1.5*IQR) — same as scanner profiling
- Historical range: min/max, p05/p95 for evidence

Each anomaly contains: baseline mean/std/current, z-score, threshold, historical range, evidence, affected column.
"""
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import desc
import models

def _mean_std(values: List[float]) -> Tuple[float, float]:
    arr = np.array(values, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=0)) if len(arr) > 1 else 0.0
    return mean, std

def _percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(values, q*100))

def _is_anomalous_zscore(current: float, historical: List[float], warn_z: float = 2.0, crit_z: float = 3.0) -> Tuple[bool, str, float, Dict[str, Any]]:
    """
    Returns (is_anomaly, severity, z_score, evidence)
    Uses z-score if n>=5 and std>0 else IQR.
    """
    if len(historical) < 3:
        return False, "INFO", 0.0, {"reason": "insufficient_history (<3)"}
    mean, std = _mean_std(historical)
    # IQR fallback if std==0 or n<5
    if std == 0 or len(historical) < 5:
        # IQR method
        q1 = _percentile(historical, 0.25)
        q3 = _percentile(historical, 0.75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        if current < lower or current > upper:
            # Determine severity by distance beyond fence
            dist = min(abs(current - lower), abs(current - upper)) if iqr > 0 else abs(current - mean)
            severity = "CRITICAL" if dist > iqr else "WARNING"
            evidence = {
                "method": "IQR",
                "historical_q1": round(q1, 3),
                "historical_q3": round(q3, 3),
                "iqr": round(iqr, 3),
                "lower_fence": round(lower, 3),
                "upper_fence": round(upper, 3),
                "current": round(current, 3),
                "historical_range": [round(min(historical),3), round(max(historical),3)],
                "historical_mean": round(mean, 3),
            }
            return True, severity, round((current-mean)/std if std>0 else 0, 2), evidence
        return False, "INFO", 0.0, {"method": "IQR", "lower_fence": round(lower,3), "upper_fence": round(upper,3), "current": round(current,3)}
    # z-score
    z = (current - mean) / std if std != 0 else 0.0
    abs_z = abs(z)
    if abs_z >= crit_z:
        severity = "CRITICAL"
    elif abs_z >= warn_z:
        severity = "WARNING"
    else:
        return False, "INFO", round(z, 2), {"method": "z-score", "z": round(z,2), "mean": round(mean,3), "std": round(std,3)}
    evidence = {
        "method": "z-score",
        "z_score": round(z, 2),
        "threshold_warning": warn_z,
        "threshold_critical": crit_z,
        "historical_mean": round(mean, 3),
        "historical_std": round(std, 3),
        "historical_min": round(min(historical),3),
        "historical_max": round(max(historical),3),
        "historical_p05": round(_percentile(historical, 0.05),3),
        "historical_p95": round(_percentile(historical, 0.95),3),
        "current": round(current, 3),
        "delta": round(current - mean, 3),
    }
    return True, severity, round(z, 2), evidence

def detect_null_rate_anomalies(
    db: Session,
    dataset_name: str,
    column: str,
    current_null_rate: float,
    window: int = 10,
) -> List[Dict[str, Any]]:
    """Historical null_rate per column (from schema_columns)."""
    # Find logical datasets
    prefix = dataset_name.split("_")[0] if dataset_name else dataset_name
    related = db.query(models.Dataset).filter(models.Dataset.name.like(f"{prefix}%")).all()
    ids = [d.id for d in related] if related else []
    if not ids:
        return []
    # Get historical schemas and columns
    # Order by created_at desc, take window
    schemas = db.query(models.SchemaRecord).filter(models.SchemaRecord.dataset_id.in_(ids)).order_by(desc(models.SchemaRecord.created_at)).limit(window+1).all()
    # Exclude the most recent (current) if it matches current_null_rate? For simplicity, take all and if current is latest, historical is rest
    historical_rates: List[float] = []
    for sch in schemas:
        col = db.query(models.SchemaColumn).filter(models.SchemaColumn.schema_id == sch.id, models.SchemaColumn.column_name == column).first()
        if col and col.null_rate is not None:
            # If this is the current schema (maybe the latest), we skip if its rate == current_null_rate (avoid self-compare)
            # But we don't know which is current; we just collect all and if current matches one, we exclude one occurrence
            historical_rates.append(float(col.null_rate))
    # If current_null_rate is in historical, remove one occurrence (the current)
    # This is heuristic to avoid comparing to self
    if current_null_rate in historical_rates:
        # Remove first occurrence
        historical_rates.remove(current_null_rate)
        # If we removed, we need window-1? But we already limited to window+1, so after removal we have window
    else:
        # If current is new (not yet stored as schema? For scan anomalies, current may not yet be in DB as schema? But for anomaly detection via scan, current is from scan's df, not yet historical)
        # For scan-based, historical is previous schemas
        historical_rates = historical_rates[:window]
    # Trim to window
    historical_rates = historical_rates[:window]
    if len(historical_rates) < 3:
        return []
    is_anom, severity, z, evidence = _is_anomalous_zscore(current_null_rate, historical_rates)
    if is_anom:
        return [{
            "anomaly_type": "NULL_RATE_ANOMALY",
            "severity": severity,
            "column": column,
            "dataset": dataset_name,
            "current_null_rate": round(current_null_rate, 4),
            "historical_mean": evidence.get("historical_mean"),
            "historical_std": evidence.get("historical_std"),
            "z_score": z,
            "evidence": evidence,
            "description": f"Null rate anomaly on {column}: {current_null_rate:.3f} vs historical mean {evidence.get('historical_mean', 0):.3f} (z={z:.1f}, {severity.lower()})",
        }]
    return []

def detect_quality_score_anomaly(
    db: Session,
    dataset_name: str,
    current_score: float,
    window: int = 10,
) -> List[Dict[str, Any]]:
    """Historical quality_score per logical dataset (from scans)."""
    prefix = dataset_name.split("_")[0] if dataset_name else dataset_name
    related = db.query(models.Dataset).filter(models.Dataset.name.like(f"{prefix}%")).all()
    ids = [d.id for d in related] if related else []
    if not ids:
        return []
    scans = db.query(models.Scan).filter(models.Scan.dataset_id.in_(ids)).order_by(desc(models.Scan.completed_at)).limit(window+1).all()
    # Exclude current scan if its score == current_score
    historical_scores: List[float] = []
    for s in scans:
        if s.quality_score is not None:
            if float(s.quality_score) == current_score and len(historical_scores) == 0:
                # Skip first if it matches current (likely self)
                continue
            historical_scores.append(float(s.quality_score))
    historical_scores = historical_scores[:window]
    if len(historical_scores) < 3:
        return []
    is_anom, severity, z, evidence = _is_anomalous_zscore(current_score, historical_scores)
    # For quality score, lower is worse, so we only flag if current < mean (degradation)
    if is_anom and current_score < evidence.get("historical_mean", 0):
        return [{
            "anomaly_type": "QUALITY_SCORE_ANOMALY",
            "severity": severity,
            "dataset": dataset_name,
            "current_score": round(current_score, 1),
            "historical_mean": evidence.get("historical_mean"),
            "z_score": z,
            "evidence": evidence,
            "description": f"Quality score anomaly: {current_score:.1f} vs historical mean {evidence.get('historical_mean'):.1f} (z={z:.1f})",
        }]
    return []

def detect_row_count_anomaly(
    db: Session,
    dataset_name: str,
    current_count: int,
    window: int = 10,
) -> List[Dict[str, Any]]:
    """Historical row_count per logical dataset."""
    prefix = dataset_name.split("_")[0] if dataset_name else dataset_name
    related = db.query(models.Dataset).filter(models.Dataset.name.like(f"{prefix}%")).all()
    ids = [d.id for d in related] if related else []
    if not ids:
        return []
    # Get datasets ordered by created_at
    datasets = db.query(models.Dataset).filter(models.Dataset.id.in_(ids)).order_by(desc(models.Dataset.created_at)).limit(window+1).all()
    historical_counts = [d.row_count for d in datasets if d.row_count != current_count]
    # If current dataset is latest, its count is included; we should exclude one if matches
    historical_counts = historical_counts[:window]
    if len(historical_counts) < 3:
        return []
    # Convert to float for z-score
    is_anom, severity, z, evidence = _is_anomalous_zscore(float(current_count), [float(c) for c in historical_counts])
    if is_anom:
        return [{
            "anomaly_type": "ROW_COUNT_ANOMALY",
            "severity": severity,
            "dataset": dataset_name,
            "current_row_count": current_count,
            "historical_mean": evidence.get("historical_mean"),
            "z_score": z,
            "evidence": evidence,
            "description": f"Row count anomaly: {current_count} vs historical mean {evidence.get('historical_mean'):.1f} (z={z:.1f})",
        }]
    return []

def detect_anomalies_for_scan(
    db: Session,
    scan_id: int,
    window: int = 10,
) -> List[Dict[str, Any]]:
    """Detect anomalies for a scan by comparing its metrics to historical window."""
    scan = db.query(models.Scan).filter(models.Scan.id == scan_id).first()
    if not scan or not scan.dataset:
        return []
    dataset = scan.dataset
    # Quality score anomaly
    anomalies = []
    if scan.quality_score is not None:
        anomalies.extend(detect_quality_score_anomaly(db, dataset.name, float(scan.quality_score), window=window))
    # Row count anomaly (using dataset row_count)
    anomalies.extend(detect_row_count_anomaly(db, dataset.name, dataset.row_count, window=window))
    # Null rate per column anomalies (need current scan's schema)
    schema = db.query(models.SchemaRecord).filter(models.SchemaRecord.dataset_id == dataset.id).order_by(desc(models.SchemaRecord.created_at)).first()
    if schema:
        for col in schema.columns:
            if col.null_rate is not None:
                anomalies.extend(detect_null_rate_anomalies(db, dataset.name, col.column_name, float(col.null_rate), window=window))
    return anomalies

def detect_anomalies_for_dataset(
    db: Session,
    dataset_name: str,
    window: int = 10,
) -> Dict[str, Any]:
    """Aggregated anomalies for a logical dataset (latest scan vs history)."""
    # Find latest dataset for this logical name
    prefix = dataset_name.split("_")[0] if dataset_name else dataset_name
    related = db.query(models.Dataset).filter(models.Dataset.name.like(f"{prefix}%")).order_by(desc(models.Dataset.created_at)).first()
    if not related:
        return {"dataset": dataset_name, "anomalies": [], "status": "no_data"}
    # Find latest scan for that dataset
    latest_scan = db.query(models.Scan).filter(models.Scan.dataset_id == related.id).order_by(desc(models.Scan.completed_at)).first()
    if not latest_scan:
        return {"dataset": dataset_name, "anomalies": [], "status": "no_scan"}
    anomalies = detect_anomalies_for_scan(db, latest_scan.id, window=window)
    status = "anomalous" if anomalies else "healthy"
    return {
        "dataset": dataset_name,
        "logical_prefix": prefix,
        "latest_scan_id": latest_scan.id,
        "latest_dataset_id": related.id,
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
        "status": status,
        "window": window,
    }
