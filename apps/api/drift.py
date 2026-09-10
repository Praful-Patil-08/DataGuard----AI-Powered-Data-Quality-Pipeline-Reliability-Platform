from typing import List, Dict, Any, Optional

SEVERITY_ORDER = {"INFO": 0, "WARNING": 1, "CRITICAL": 2, "PASSED": 0, "info": 0, "warning": 1, "critical": 2}

def _ratio_delta(baseline: float, candidate: float) -> float:
    """Adapted from Watchtower _ratio_delta:634"""
    if baseline == 0:
        if candidate == 0:
            return 0.0
        return 1.0
    return round((candidate - baseline) / abs(baseline), 3)

def detect_schema_drift(
    baseline_columns: List[Dict[str, Any]],
    current_columns: List[Dict[str, Any]],
    baseline_row_count: Optional[int] = None,
    current_row_count: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Compares baseline schema columns against current schema columns deterministically.
    Returns a list of structured issue dictionaries.
    Enhanced with Watchtower drift detection: null-rate, cardinality, numeric, row-count.
    """
    issues = []

    baseline_map = {col["column_name"]: col for col in baseline_columns}
    current_map = {col["column_name"]: col for col in current_columns}

    # 1. Detect COLUMN_REMOVED
    for col_name, base_col in baseline_map.items():
        if col_name not in current_map:
            severity = "CRITICAL"
            issues.append({
                "issue_type": "COLUMN_REMOVED",
                "severity": severity,
                "column_name": col_name,
                "description": f"Column '{col_name}' was present in baseline schema ({base_col['data_type']}) but removed in current dataset.",
                "metadata": {
                    "previous_type": base_col["data_type"],
                    "previous_nullable": base_col["nullable"],
                }
            })

    # 2. Detect COLUMN_ADDED
    for col_name, curr_col in current_map.items():
        if col_name not in baseline_map:
            issues.append({
                "issue_type": "COLUMN_ADDED",
                "severity": "WARNING",
                "column_name": col_name,
                "description": f"New column '{col_name}' ({curr_col['data_type']}) added that was not present in baseline schema.",
                "metadata": {
                    "current_type": curr_col["data_type"],
                    "current_nullable": curr_col["nullable"],
                }
            })

    # 3. Detect TYPE_CHANGED, NULLABILITY_CHANGED and Watchtower drifts
    for col_name in baseline_map.keys() & current_map.keys():
        base_col = baseline_map[col_name]
        curr_col = current_map[col_name]

        # Datatype change
        if base_col["data_type"] != curr_col["data_type"]:
            breaking_transitions = {
                ("FLOAT", "STRING"),
                ("INTEGER", "STRING"),
                ("DATE", "STRING"),
                ("INTEGER", "BOOLEAN"),
                ("FLOAT", "INTEGER"),
            }
            is_breaking = (base_col["data_type"], curr_col["data_type"]) in breaking_transitions or curr_col["data_type"] == "STRING"
            severity = "CRITICAL" if is_breaking else "WARNING"

            issues.append({
                "issue_type": "TYPE_CHANGED",
                "severity": severity,
                "column_name": col_name,
                "description": f"Column '{col_name}' changed type from {base_col['data_type']} to {curr_col['data_type']}.",
                "metadata": {
                    "previous_type": base_col["data_type"],
                    "current_type": curr_col["data_type"],
                }
            })

        # Nullability change (structural)
        if not base_col.get("nullable") and curr_col.get("nullable"):
            issues.append({
                "issue_type": "NULLABILITY_CHANGED",
                "severity": "WARNING",
                "column_name": col_name,
                "description": f"Column '{col_name}' was previously non-nullable, but current dataset contains {curr_col.get('null_count', 0)} null values.",
                "metadata": {
                    "previous_nullable": False,
                    "current_nullable": True,
                    "null_count": curr_col.get("null_count", 0),
                }
            })

        # --- Watchtower: Null-rate drift (abs delta >= 0.05) ---
        base_null_rate = base_col.get("null_rate")
        curr_null_rate = curr_col.get("null_rate")
        if base_null_rate is not None and curr_null_rate is not None:
            # Fallback compute if null_rate not stored but counts available
            if base_null_rate is None and baseline_row_count:
                base_null_rate = round(base_col.get("null_count", 0) / baseline_row_count, 3)
            if curr_null_rate is None and current_row_count:
                curr_null_rate = round(curr_col.get("null_count", 0) / current_row_count, 3)
            null_delta = round(curr_null_rate - base_null_rate, 3)
            if abs(null_delta) >= 0.05:
                severity = "CRITICAL" if abs(null_delta) >= 0.2 else "WARNING"
                issues.append({
                    "issue_type": "NULL_RATE_DRIFT",
                    "severity": severity,
                    "column_name": col_name,
                    "description": f"Column '{col_name}' null rate shifted from {base_null_rate:.3f} to {curr_null_rate:.3f} (delta {null_delta:+.3f}).",
                    "metadata": {
                        "baseline_null_rate": base_null_rate,
                        "candidate_null_rate": curr_null_rate,
                        "delta": null_delta,
                    }
                })

        # --- Watchtower: Cardinality drift ---
        base_unique_ratio = base_col.get("unique_ratio")
        curr_unique_ratio = curr_col.get("unique_ratio")
        base_unique_count = base_col.get("unique_count", 0)
        curr_unique_count = curr_col.get("unique_count", 0)
        if base_unique_ratio is not None and curr_unique_ratio is not None:
            unique_ratio_delta = round(curr_unique_ratio - base_unique_ratio, 3)
            unique_count_ratio = _ratio_delta(float(base_unique_count), float(curr_unique_count))
            if unique_ratio_delta <= -0.2 or (base_unique_ratio < 0.9 and unique_count_ratio <= -0.3):
                is_severe = unique_count_ratio <= -0.5 or unique_ratio_delta <= -0.4
                severity = "CRITICAL" if is_severe else "WARNING"
                issues.append({
                    "issue_type": "CARDINALITY_DRIFT",
                    "severity": severity,
                    "column_name": col_name,
                    "description": f"Column '{col_name}' cardinality collapsed from {base_unique_count} to {curr_unique_count} (ratio {unique_count_ratio:+.3f}, unique_ratio {base_unique_ratio:.3f} -> {curr_unique_ratio:.3f}).",
                    "metadata": {
                        "baseline_unique_count": base_unique_count,
                        "candidate_unique_count": curr_unique_count,
                        "baseline_unique_ratio": base_unique_ratio,
                        "candidate_unique_ratio": curr_unique_ratio,
                        "unique_count_delta_ratio": unique_count_ratio,
                        "unique_ratio_delta": unique_ratio_delta,
                    }
                })

        # --- Watchtower: Numeric distribution drift ---
        base_mean = base_col.get("mean")
        curr_mean = curr_col.get("mean")
        base_outlier_rate = base_col.get("outlier_rate")
        curr_outlier_rate = curr_col.get("outlier_rate")
        # Only for numeric columns where stats exist
        if base_mean is not None and curr_mean is not None and base_outlier_rate is not None and curr_outlier_rate is not None:
            try:
                mean_delta_ratio = _ratio_delta(float(base_mean), float(curr_mean))
                outlier_delta = round(float(curr_outlier_rate) - float(base_outlier_rate), 3)
                if abs(mean_delta_ratio) >= 0.2 or abs(outlier_delta) >= 0.05:
                    is_severe = abs(mean_delta_ratio) >= 0.5 or abs(outlier_delta) >= 0.15
                    severity = "CRITICAL" if is_severe else "WARNING"
                    issues.append({
                        "issue_type": "NUMERIC_DRIFT",
                        "severity": severity,
                        "column_name": col_name,
                        "description": f"Column '{col_name}' numeric distribution shifted (mean {base_mean:.3f} -> {curr_mean:.3f} delta {mean_delta_ratio:+.3f}, outliers {base_outlier_rate:.3f} -> {curr_outlier_rate:.3f}).",
                        "metadata": {
                            "baseline_mean": round(float(base_mean), 3),
                            "candidate_mean": round(float(curr_mean), 3),
                            "mean_delta_ratio": mean_delta_ratio,
                            "baseline_outlier_rate": float(base_outlier_rate),
                            "candidate_outlier_rate": float(curr_outlier_rate),
                            "outlier_delta": outlier_delta,
                        }
                    })
            except Exception:
                pass

    # --- Row-count drift ---
    if baseline_row_count is not None and current_row_count is not None and baseline_row_count > 0:
        row_delta = current_row_count - baseline_row_count
        row_delta_ratio = _ratio_delta(float(baseline_row_count), float(current_row_count))
        # Trigger if drop or gain is significant
        if abs(row_delta_ratio) >= 0.15:
            severity = "CRITICAL" if abs(row_delta_ratio) >= 0.25 else "WARNING"
            issues.append({
                "issue_type": "ROW_COUNT_DRIFT",
                "severity": severity,
                "column_name": None,
                "description": f"Row count shifted from {baseline_row_count} to {current_row_count} (delta {row_delta:+d}, ratio {row_delta_ratio:+.3f}).",
                "metadata": {
                    "baseline_row_count": baseline_row_count,
                    "candidate_row_count": current_row_count,
                    "row_count_delta": row_delta,
                    "row_count_delta_ratio": row_delta_ratio,
                }
            })

    return issues

def generate_incident_summary(issues: List[Dict[str, Any]], baseline_row_count: Optional[int] = None, current_row_count: Optional[int] = None) -> tuple[str, str]:
    """
    Generates plain-English incident summary and severity - adapted from Watchtower _incident_report:642
    Returns (summary, severity) where severity is INFO/WARNING/CRITICAL
    """
    # Categorize issues
    removed = [i for i in issues if i["issue_type"] == "COLUMN_REMOVED"]
    type_changes = [i for i in issues if i["issue_type"] == "TYPE_CHANGED"]
    added = [i for i in issues if i["issue_type"] == "COLUMN_ADDED"]
    null_drifts = [i for i in issues if i["issue_type"] == "NULL_RATE_DRIFT"]
    numeric_drifts = [i for i in issues if i["issue_type"] == "NUMERIC_DRIFT"]
    cardinality_drifts = [i for i in issues if i["issue_type"] == "CARDINALITY_DRIFT"]
    row_drifts = [i for i in issues if i["issue_type"] == "ROW_COUNT_DRIFT"]

    severe_nulls = [i for i in null_drifts if abs(i["metadata"]["delta"]) >= 0.2]
    severe_numeric = [i for i in numeric_drifts if abs(i["metadata"]["mean_delta_ratio"]) >= 0.5 or abs(i["metadata"]["outlier_delta"]) >= 0.15]
    severe_cardinality = [i for i in cardinality_drifts if i["metadata"]["unique_count_delta_ratio"] <= -0.5 or i["metadata"]["unique_ratio_delta"] <= -0.4]

    row_delta_ratio = 0.0
    if baseline_row_count and current_row_count and baseline_row_count != 0:
        row_delta_ratio = abs(_ratio_delta(float(baseline_row_count), float(current_row_count)))

    # Critical conditions
    if removed or type_changes or row_delta_ratio >= 0.25 or severe_cardinality:
        parts = []
        if removed:
            parts.append(f"columns removed: {', '.join(i['column_name'] for i in removed)}")
        if type_changes:
            parts.append("type changes: " + ", ".join(f"{i['column_name']} ({i['metadata']['previous_type']} -> {i['metadata']['current_type']})" for i in type_changes))
        if row_delta_ratio >= 0.25 and baseline_row_count is not None:
            parts.append(f"row count moved from {baseline_row_count} to {current_row_count}")
        if severe_cardinality:
            worst = severe_cardinality[0]
            parts.append(f"cardinality collapse on {worst['column_name']} ({worst['metadata']['baseline_unique_count']} -> {worst['metadata']['candidate_unique_count']})")
        return ("Critical incident: " + "; ".join(parts) + ".", "CRITICAL")

    # Warning conditions
    if added or severe_nulls or severe_numeric or cardinality_drifts or row_drifts or null_drifts or numeric_drifts:
        parts = []
        if added:
            parts.append(f"new columns detected: {', '.join(i['column_name'] for i in added)}")
        if severe_nulls:
            worst = severe_nulls[0]
            parts.append(f"null-rate drift on {worst['column_name']} ({worst['metadata']['baseline_null_rate']:.3f} -> {worst['metadata']['candidate_null_rate']:.3f})")
        if severe_numeric:
            worst = severe_numeric[0]
            parts.append(f"numeric shift on {worst['column_name']} (mean delta {worst['metadata']['mean_delta_ratio']:+.3f}, outlier delta {worst['metadata']['outlier_delta']:+.3f})")
        elif cardinality_drifts:
            worst = cardinality_drifts[0]
            parts.append(f"cardinality drift on {worst['column_name']} ({worst['metadata']['baseline_unique_count']} -> {worst['metadata']['candidate_unique_count']})")
        elif row_drifts:
            worst = row_drifts[0]
            parts.append(f"row count drift {worst['metadata']['row_count_delta_ratio']:+.3f}")
        elif null_drifts:
            worst = null_drifts[0]
            parts.append(f"null-rate drift on {worst['column_name']} ({worst['metadata']['delta']:+.3f})")
        elif numeric_drifts:
            worst = numeric_drifts[0]
            parts.append(f"numeric drift on {worst['column_name']} ({worst['metadata']['mean_delta_ratio']:+.3f})")
        return ("Warning incident: " + "; ".join(parts) + ".", "WARNING")

    return "Healthy profile change: no material schema or value drift detected.", "INFO"

def assess_gate(
    issues: List[Dict[str, Any]],
    incident_severity: str,
    baseline_row_count: Optional[int] = None,
    current_row_count: Optional[int] = None,
    allowed_severity: str = "WARNING",
    max_row_count_drop_ratio: float = 0.15,
    max_null_drift_count: int = 0,
    max_numeric_drift_count: int = 0,
    max_cardinality_drift_count: int = 0,
) -> Dict[str, Any]:
    """
    Assesses if a scan passes quality gate - adapted from Watchtower assess_gate:255
    Returns dict with passed, reasons, thresholds
    """
    reasons: List[str] = []
    # Normalize severity comparison
    sev_order = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
    incident_level = sev_order.get(incident_severity, 0)
    allowed_level = sev_order.get(allowed_severity, 1)
    if incident_level > allowed_level:
        reasons.append(f"incident severity {incident_severity} exceeded allowed {allowed_severity}")

    if baseline_row_count is not None and current_row_count is not None and baseline_row_count != 0:
        row_drop_ratio = max(0.0, round(-_ratio_delta(float(baseline_row_count), float(current_row_count)), 3))
        if row_drop_ratio > max_row_count_drop_ratio:
            reasons.append(f"row-count drop {row_drop_ratio:.3f} exceeded limit {max_row_count_drop_ratio:.3f}")

    null_drift_count = sum(1 for i in issues if i["issue_type"] == "NULL_RATE_DRIFT")
    if null_drift_count > max_null_drift_count:
        reasons.append(f"null-rate drift count {null_drift_count} exceeded limit {max_null_drift_count}")

    numeric_drift_count = sum(1 for i in issues if i["issue_type"] == "NUMERIC_DRIFT")
    if numeric_drift_count > max_numeric_drift_count:
        reasons.append(f"numeric drift count {numeric_drift_count} exceeded limit {max_numeric_drift_count}")

    cardinality_drift_count = sum(1 for i in issues if i["issue_type"] == "CARDINALITY_DRIFT")
    if cardinality_drift_count > max_cardinality_drift_count:
        reasons.append(f"cardinality drift count {cardinality_drift_count} exceeded limit {max_cardinality_drift_count}")

    return {
        "passed": not reasons,
        "reasons": reasons,
        "allowed_severity": allowed_severity,
        "max_row_count_drop_ratio": max_row_count_drop_ratio,
        "max_null_drift_count": max_null_drift_count,
        "max_numeric_drift_count": max_numeric_drift_count,
        "max_cardinality_drift_count": max_cardinality_drift_count,
        "incident_severity": incident_severity,
    }
