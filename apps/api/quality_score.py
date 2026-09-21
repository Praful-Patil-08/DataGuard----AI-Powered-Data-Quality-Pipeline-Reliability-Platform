"""
Quality Score — deterministic, explainable 0-100 with dimensions.

Design study:
- Soda Core: per-check threshold + overall scan status but no unified score
- Great Expectations: ValidationResult success flag per expectation, no unified score
- Elementary (dbt): anomaly detection + historical reliability trends, not score
- OpenMetadata: Data Quality dimensions (completeness, validity, uniqueness) with weights

DataGuard native:
- 7 dimensions: completeness, uniqueness, validity, consistency, schema_stability,
  distribution_stability, freshness — weighted sum, each 0-100, explainable penalty
- No ML, no false precision: integer 0-100, penalty per CRITICAL 25 / WARNING 10,
  clamped, plus profiling-derived freshness bonus/penalty
- Separate from issues: score is deterministic aggregation; AI never computes score

Weights sum to 1.0; freshness neutral (100) if no date column so no penalty.
All penalties deterministic, reproducible, and explainable via dimension breakdown.
"""
from typing import List, Dict, Any, Optional
import pandas as pd
import datetime

# Dimension weights (must sum 1.0)
DIMENSION_WEIGHTS: Dict[str, float] = {
    "completeness": 0.20,
    "uniqueness": 0.20,
    "validity": 0.20,
    "consistency": 0.10,
    "schema_stability": 0.15,
    "distribution_stability": 0.10,
    "freshness": 0.05,
}

# Mapping issue_type -> dimension (single assignment to avoid double penalty)
ISSUE_TO_DIMENSION: Dict[str, str] = {
    # completeness
    "HIGH_NULL_RATE": "completeness",
    "PRIMARY_KEY_NULL": "completeness",
    "CONTRACT_BREACH_COMPLETENESS": "completeness",
    "NULL_RATE_DRIFT": "completeness",
    "EMPTY_DATASET": "completeness",
    # uniqueness
    "DUPLICATE_PRIMARY_KEY": "uniqueness",
    "DUPLICATE_ROWS": "uniqueness",
    "CARDINALITY_DRIFT": "uniqueness",
    "CONTRACT_BREACH_UNIQUENESS": "uniqueness",
    # validity
    "NEGATIVE_VALUE_ANOMALY": "validity",
    "NUMERIC_ANOMALY": "validity",
    "MALFORMED_DATE": "validity",
    "CONTRACT_BREACH_RANGE": "validity",
    "CONTRACT_BREACH_REGEX": "validity",
    # consistency
    "CATEGORICAL_INCONSISTENCY": "consistency",
    # schema_stability
    "COLUMN_REMOVED": "schema_stability",
    "COLUMN_ADDED": "schema_stability",
    "TYPE_CHANGED": "schema_stability",
    "NULLABILITY_CHANGED": "schema_stability",
    # distribution_stability
    "NUMERIC_DRIFT": "distribution_stability",
    "ROW_COUNT_DRIFT": "distribution_stability",
    "CONTRACT_BREACH_ROW_COUNT": "distribution_stability",
    # contract evaluation errors -> validity? Keep neutral
    "CONTRACT_EVALUATION_ERROR": "validity",
    "CONTRACT_UNKNOWN_TYPE": "validity",
    "RULE_EXECUTION_ERROR": "validity",
    # schema evolution
    "COLUMN_RENAMED_CANDIDATE": "schema_stability",
    # statistical drift (Phase 5 PSI/KS/JSD)
    "NUMERIC_PSI_DRIFT": "distribution_stability",
    "NUMERIC_KS_DRIFT": "distribution_stability",
    "CATEGORICAL_PSI_DRIFT": "distribution_stability",
    "CATEGORICAL_JSD_DRIFT": "distribution_stability",
}

def _freshness_score(df: Optional[pd.DataFrame]) -> tuple[int, str]:
    """
    Freshness dimension: checks max date vs now.
    If no date column, score 100 neutral (explain: no date column to evaluate).
    If date column exists, days_since = now - max_date; penalty -20 if >30d, -40 if >90d.
    Deterministic: uses UTC now.
    """
    if df is None or df.empty:
        return 100, "No data for freshness check — neutral 100."
    # Find date columns via dtype or name
    date_cols = []
    for col in df.columns:
        if "date" in col.lower() or "time" in col.lower():
            date_cols.append(col)
            continue
        # Try dtype inference via scanner infer?
        try:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                date_cols.append(col)
        except Exception:
            pass
    if not date_cols:
        return 100, "No date/time column detected — freshness neutral 100."
    # Collect max date across date cols
    max_date = None
    for col in date_cols:
        try:
            series = pd.to_datetime(df[col], errors="coerce").dropna()
            if len(series) > 0:
                col_max = series.max()
                if max_date is None or col_max > max_date:
                    max_date = col_max
        except Exception:
            continue
    if max_date is None or pd.isna(max_date):
        return 100, "Date column present but no valid dates — neutral 100."
    try:
        now = pd.Timestamp(datetime.datetime.now(datetime.timezone.utc))
        # Make max_date tz-aware if naive
        if max_date.tzinfo is None:
            max_date = max_date.tz_localize("UTC") if hasattr(max_date, "tz_localize") else pd.Timestamp(max_date, tz="UTC")
        # Ensure both tz-aware for diff
        if max_date.tzinfo is None:
            max_date = pd.Timestamp(max_date).tz_localize("UTC")
        days_since = (now - max_date).days
        if days_since <= 7:
            return 100, f"Fresh: max date {max_date.date()} is {days_since}d ago — 100."
        elif days_since <= 30:
            # slight penalty -5
            return 95, f"Moderate freshness: max date {max_date.date()} is {days_since}d ago — 95."
        elif days_since <= 90:
            return 80, f"Stale: max date {max_date.date()} is {days_since}d ago — 80."
        else:
            return 60, f"Very stale: max date {max_date.date()} is {days_since}d ago — 60."
    except Exception as e:
        return 100, f"Freshness check failed: {str(e)[:60]} — neutral 100."

def compute_dimension_scores(
    issues: List[Dict[str, Any]],
    df: Optional[pd.DataFrame] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Compute per-dimension scores 0-100 with evidence.
    Penalty: CRITICAL -25, WARNING -10 per issue in dimension, clamped 0-100.
    Returns dict dimension -> {score, weight, critical, warning, issues, evidence}
    """
    # Init counters
    dim_counts: Dict[str, Dict[str, int]] = {dim: {"critical": 0, "warning": 0, "issues": []} for dim in DIMENSION_WEIGHTS}
    # Map issues to dimensions
    for iss in issues:
        itype = iss.get("issue_type", "")
        dim = ISSUE_TO_DIMENSION.get(itype)
        if not dim:
            # Fallback heuristic: assign unknown critical to validity
            # This keeps score conservative
            dim = "validity"
        # Count
        sev = iss.get("severity", "WARNING")
        if sev == "CRITICAL":
            dim_counts[dim]["critical"] += 1
        elif sev == "WARNING":
            dim_counts[dim]["warning"] += 1
        else:
            dim_counts[dim]["warning"] += 0  # INFO not penalized
        dim_counts[dim]["issues"].append(iss)

    dimensions: Dict[str, Dict[str, Any]] = {}
    for dim, weight in DIMENSION_WEIGHTS.items():
        if dim == "freshness":
            score, evidence = _freshness_score(df)
            # Apply issue penalties for freshness? No issue type maps to freshness yet, but if we add FRESHNESS_BREACH later
            # For now, freshness only from date recency
            # If there are issues mapped to freshness (none), they would have been counted above, but we treat freshness specially
            # So we keep score from recency, no extra penalty unless issues exist (none)
            # If issues somehow map to freshness, apply penalty as well
            counts = dim_counts[dim]
            # For freshness, we already computed recency score; now apply extra penalty if issues exist (should be 0)
            penalty = counts["critical"] * 25 + counts["warning"] * 10
            score = max(0, score - penalty)
            dimensions[dim] = {
                "score": int(score),
                "weight": weight,
                "critical": counts["critical"],
                "warning": counts["warning"],
                "evidence": evidence,
                "issues": [i["issue_type"] for i in counts["issues"]],
            }
        else:
            counts = dim_counts[dim]
            penalty = counts["critical"] * 25 + counts["warning"] * 10
            score = max(0, 100 - penalty)
            # Evidence string
            if counts["critical"] == 0 and counts["warning"] == 0:
                evidence = f"No {dim} issues — 100."
            else:
                evidence = f"{counts['critical']} critical, {counts['warning']} warning in {dim} — penalty {penalty} → {score}."
            dimensions[dim] = {
                "score": int(score),
                "weight": weight,
                "critical": counts["critical"],
                "warning": counts["warning"],
                "evidence": evidence,
                "issues": [i["issue_type"] for i in counts["issues"]],
            }
    return dimensions

def compute_quality_score(
    issues: List[Dict[str, Any]],
    df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    Compute overall quality score 0-100 as weighted sum of dimensions.
    Deterministic, explainable, reproducible.
    Returns {score, dimensions, summary}
    """
    dimensions = compute_dimension_scores(issues, df)
    # Weighted sum (weights sum 1.0, so overall is 0-100)
    overall = sum(dim["score"] * dim["weight"] for dim in dimensions.values())
    overall = int(round(overall))
    # Clamp
    overall = max(0, min(100, overall))
    # Summary
    if overall >= 90:
        summary = f"Excellent quality: {overall}/100 — all dimensions healthy."
    elif overall >= 75:
        summary = f"Good quality: {overall}/100 — minor issues, monitor."
    elif overall >= 50:
        summary = f"Degraded quality: {overall}/100 — requires attention."
    else:
        summary = f"Critical quality: {overall}/100 — immediate remediation required."
    # Add lowest dimension hint
    lowest = min(dimensions.items(), key=lambda x: x[1]["score"])
    if lowest[1]["score"] < 80:
        summary += f" Weakest: {lowest[0]} ({lowest[1]['score']})."
    return {
        "score": overall,
        "dimensions": dimensions,
        "summary": summary,
    }

# Backwards compat alias
def calculate_quality_score(issues: List[Dict[str, Any]], df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    return compute_quality_score(issues, df)
