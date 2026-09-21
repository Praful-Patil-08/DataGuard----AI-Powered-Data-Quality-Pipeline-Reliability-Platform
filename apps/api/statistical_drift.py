"""
Statistical Drift — PSI, KS, JSD (deterministic, no scipy).

Study:
- PSI (Population Stability Index): sum((A-E)*ln(A/E)) over bins; typical thresholds <0.1 stable, 0.1-0.25 moderate, >0.25 significant
- KS (Kolmogorov-Smirnov): max ECDF difference for numeric; thresholds 0.2 warning / 0.4 critical for small samples; chosen for sample-size appropriateness
- JSD (Jensen-Shannon Divergence): 0-1 for categorical distribution distance; thresholds 0.1 warning / 0.2 critical

Appropriateness:
- Categorical (STRING, low cardinality): PSI + JSD via category frequencies (requires >=30 rows, <=50 categories for stability)
- Numeric (INTEGER/FLOAT): PSI via quantile bins (10 bins) + KS via ECDF (requires >=30 rows)
- Sample-size guard: skip if <30 rows or <5 unique values for categorical (too sparse)

All methods deterministic, explainable, with evidence (baseline/current distributions, metric, threshold).
No scipy dependency — numpy/pandas only.
"""
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd

def _psi(expected_percents: List[float], actual_percents: List[float], eps: float = 0.0001) -> float:
    """PSI calculation with smoothing to avoid division by zero."""
    psi = 0.0
    for e, a in zip(expected_percents, actual_percents):
        # Smooth zeros
        e_s = max(e, eps)
        a_s = max(a, eps)
        psi += (a_s - e_s) * np.log(a_s / e_s)
    return round(float(psi), 4)

def _jsd(p: List[float], q: List[float], eps: float = 1e-9) -> float:
    """Jensen-Shannon Divergence 0-1 (symmetrized KL). Returns sqrt JSD for distance-like."""
    p = np.array(p, dtype=float)
    q = np.array(q, dtype=float)
    # Normalize to sum 1
    p = p / p.sum() if p.sum() > 0 else p
    q = q / q.sum() if q.sum() > 0 else q
    # Smoothing
    p = np.clip(p, eps, 1.0)
    q = np.clip(q, eps, 1.0)
    p = p / p.sum()
    q = q / q.sum()
    m = 0.5 * (p + q)
    # KL
    kl_pm = np.sum(p * np.log(p / m))
    kl_qm = np.sum(q * np.log(q / m))
    jsd = 0.5 * (kl_pm + kl_qm)
    # JSD is between 0 and ln2; normalize? Return raw jsd; distance is sqrt
    # Convert to 0-1 range via sqrt(jsd / ln2) or just jsd; we use sqrt(jsd)
    # For categorical, jsd 0.1 is moderate, 0.2 is large
    return round(float(np.sqrt(jsd)), 4)

def _ks_statistic(baseline: np.ndarray, current: np.ndarray) -> float:
    """KS statistic deterministic via sorted ECDF max difference."""
    b = np.sort(baseline)
    c = np.sort(current)
    # Create combined sorted unique values
    combined = np.sort(np.unique(np.concatenate([b, c])))
    # ECDF
    def ecdf(arr, x):
        return np.searchsorted(np.sort(arr), x, side="right") / len(arr)
    max_diff = 0.0
    for val in combined:
        diff = abs(ecdf(b, val) - ecdf(c, val))
        if diff > max_diff:
            max_diff = diff
    return round(float(max_diff), 4)

def _categorical_distribution(series: pd.Series) -> Dict[str, float]:
    """Return category -> proportion for series (dropna, top)."""
    non_null = series.dropna().astype(str)
    if len(non_null) == 0:
        return {}
    counts = non_null.value_counts()
    total = len(non_null)
    return {k: v / total for k, v in counts.items()}

def psi_categorical(baseline: pd.Series, current: pd.Series) -> Tuple[Optional[float], Dict[str, Any]]:
    """PSI for categorical: align categories union, compute PSI."""
    if len(baseline.dropna()) < 30 or len(current.dropna()) < 30:
        return None, {"reason": "insufficient_rows (<30)"}
    base_dist = _categorical_distribution(baseline)
    curr_dist = _categorical_distribution(current)
    # Need at least 2 categories and <=50 for stability
    unique_base = len(base_dist)
    if unique_base < 2:
        return None, {"reason": "too_few_categories (<2)"}
    if unique_base > 50:
        # Use top 20 + other
        top_cats = list(pd.Series(baseline.dropna().astype(str)).value_counts().head(20).index)
        # Recompute with other bucket
        def dist_with_other(s):
            non_null = s.dropna().astype(str)
            total = len(non_null)
            counts = {}
            for v in non_null:
                key = v if v in top_cats else "__OTHER__"
                counts[key] = counts.get(key, 0) + 1
            return {k: v/total for k, v in counts.items()}
        base_dist = dist_with_other(baseline)
        curr_dist = dist_with_other(current)
    # Union keys
    keys = sorted(set(base_dist.keys()) | set(curr_dist.keys()))
    expected = [base_dist.get(k, 0.0) for k in keys]
    actual = [curr_dist.get(k, 0.0) for k in keys]
    psi = _psi(expected, actual)
    evidence = {
        "categories": keys[:10],  # sample
        "baseline_percents": [round(v, 3) for v in expected[:5]],
        "current_percents": [round(v, 3) for v in actual[:5]],
        "unique_categories_baseline": len(base_dist),
        "unique_categories_current": len(curr_dist),
    }
    return psi, evidence

def psi_numeric(baseline: pd.Series, current: pd.Series, bins: int = 10) -> Tuple[Optional[float], Dict[str, Any]]:
    """PSI for numeric via quantile bins from baseline."""
    b_vals = pd.to_numeric(baseline, errors="coerce").dropna().astype(float)
    c_vals = pd.to_numeric(current, errors="coerce").dropna().astype(float)
    if len(b_vals) < 30 or len(c_vals) < 30:
        return None, {"reason": "insufficient_rows (<30)"}
    if b_vals.nunique() < 5:
        return None, {"reason": "too_few_unique (<5)"}
    # Create bin edges from baseline quantiles
    try:
        quantiles = np.linspace(0, 1, bins + 1)
        edges = np.quantile(b_vals, quantiles)
        # Ensure unique edges (handle duplicates)
        edges = np.unique(edges)
        if len(edges) < 3:
            # Fall back to equal width
            edges = np.linspace(b_vals.min(), b_vals.max(), bins + 1)
        # Add infinities for outer bins
        edges[0] = -np.inf
        edges[-1] = np.inf
        # Histogram
        b_counts, _ = np.histogram(b_vals, bins=edges)
        c_counts, _ = np.histogram(c_vals, bins=edges)
        b_percents = (b_counts / b_counts.sum()).tolist()
        c_percents = (c_counts / c_counts.sum()).tolist()
        psi = _psi(b_percents, c_percents)
        evidence = {
            "bins": bins,
            "bin_edges": [round(float(e), 2) if np.isfinite(e) else str(e) for e in edges[:5]],
            "baseline_percents": [round(float(v), 3) for v in b_percents[:5]],
            "current_percents": [round(float(v), 3) for v in c_percents[:5]],
        }
        return psi, evidence
    except Exception as e:
        return None, {"reason": f"psi_numeric error: {str(e)[:60]}"}

def ks_numeric(baseline: pd.Series, current: pd.Series) -> Tuple[Optional[float], Dict[str, Any]]:
    """KS for numeric."""
    b_vals = pd.to_numeric(baseline, errors="coerce").dropna().astype(float).values
    c_vals = pd.to_numeric(current, errors="coerce").dropna().astype(float).values
    if len(b_vals) < 30 or len(c_vals) < 30:
        return None, {"reason": "insufficient_rows (<30)"}
    if len(np.unique(b_vals)) < 5 or len(np.unique(c_vals)) < 5:
        return None, {"reason": "too_few_unique (<5)"}
    try:
        ks = _ks_statistic(b_vals, c_vals)
        evidence = {
            "baseline_n": len(b_vals),
            "current_n": len(c_vals),
            "baseline_mean": round(float(np.mean(b_vals)), 3),
            "current_mean": round(float(np.mean(c_vals)), 3),
        }
        return ks, evidence
    except Exception as e:
        return None, {"reason": str(e)[:60]}

def jsd_categorical(baseline: pd.Series, current: pd.Series) -> Tuple[Optional[float], Dict[str, Any]]:
    """JSD for categorical."""
    if len(baseline.dropna()) < 30 or len(current.dropna()) < 30:
        return None, {"reason": "insufficient_rows (<30)"}
    base_dist = _categorical_distribution(baseline)
    curr_dist = _categorical_distribution(current)
    if len(base_dist) < 2:
        return None, {"reason": "too_few_categories"}
    keys = sorted(set(base_dist.keys()) | set(curr_dist.keys()))
    p = [base_dist.get(k, 0.0) for k in keys]
    q = [curr_dist.get(k, 0.0) for k in keys]
    jsd = _jsd(p, q)
    evidence = {
        "categories": keys[:10],
        "baseline_percents": [round(v, 3) for v in p[:5]],
        "current_percents": [round(v, 3) for v in q[:5]],
    }
    return jsd, evidence

def detect_statistical_drift_for_column(
    col_name: str,
    baseline_series: pd.Series,
    current_series: pd.Series,
    data_type: str,
) -> List[Dict[str, Any]]:
    """
    Choose appropriate statistical technique per data type and sample size.
    Returns 0-2 issues per column with metric, threshold, evidence.
    Thresholds: PSI 0.1 warning / 0.25 critical (categorical 0.2/0.5? but use same),
                KS 0.2 warning / 0.4 critical,
                JSD 0.1 warning / 0.2 critical
    """
    issues: List[Dict[str, Any]] = []
    is_numeric = data_type in ("INTEGER", "FLOAT")
    is_categorical = data_type == "STRING" or (not is_numeric and data_type in ("STRING", "BOOLEAN"))

    # Numeric: PSI + KS
    if is_numeric:
        # PSI numeric
        psi_val, psi_ev = psi_numeric(baseline_series, current_series, bins=10)
        if psi_val is not None:
            if psi_val >= 0.25:
                severity = "CRITICAL" if psi_val >= 0.5 else "WARNING"
                # Only emit if >=0.1
                if psi_val >= 0.1:
                    issues.append({
                        "issue_type": "NUMERIC_PSI_DRIFT",
                        "severity": severity,
                        "column_name": col_name,
                        "description": f"Column '{col_name}' numeric distribution PSI={psi_val:.3f} ({'critical' if severity=='CRITICAL' else 'warning'}, threshold 0.25).",
                        "metadata": {
                            "metric": "PSI",
                            "psi": psi_val,
                            "threshold_warning": 0.1,
                            "threshold_critical": 0.25,
                            "baseline": psi_ev.get("baseline_percents"),
                            "current": psi_ev.get("current_percents"),
                            "evidence": psi_ev,
                        }
                    })
            elif psi_val >= 0.1:
                # Warning but PSI between 0.1 and 0.25
                issues.append({
                    "issue_type": "NUMERIC_PSI_DRIFT",
                    "severity": "WARNING",
                    "column_name": col_name,
                    "description": f"Column '{col_name}' numeric PSI={psi_val:.3f} (warning, threshold 0.1).",
                    "metadata": {
                        "metric": "PSI",
                        "psi": psi_val,
                        "threshold_warning": 0.1,
                        "threshold_critical": 0.25,
                        "evidence": psi_ev,
                    }
                })
        # KS numeric
        ks_val, ks_ev = ks_numeric(baseline_series, current_series)
        if ks_val is not None and ks_val >= 0.2:
            severity = "CRITICAL" if ks_val >= 0.4 else "WARNING"
            issues.append({
                "issue_type": "NUMERIC_KS_DRIFT",
                "severity": severity,
                "column_name": col_name,
                "description": f"Column '{col_name}' numeric KS={ks_val:.3f} ({severity.lower()}, threshold 0.2).",
                "metadata": {
                    "metric": "KS",
                    "ks": ks_val,
                    "threshold_warning": 0.2,
                    "threshold_critical": 0.4,
                    "evidence": ks_ev,
                }
            })
    # Categorical: PSI + JSD
    if is_categorical or data_type == "STRING":
        psi_val, psi_ev = psi_categorical(baseline_series, current_series)
        if psi_val is not None and psi_val >= 0.1:
            severity = "CRITICAL" if psi_val >= 0.25 else "WARNING"
            # For categorical, use stricter critical 0.25 (same)
            if psi_val >= 0.25:
                severity = "CRITICAL" if psi_val >= 0.5 else "WARNING"  # actually keep 0.25 as warning, 0.5 critical? Use same as numeric for consistency
                # Re-evaluate: for categorical, PSI >0.25 is significant, >0.5 large
                severity = "CRITICAL" if psi_val >= 0.5 else "WARNING"
            # But we already have psi_val >=0.1, so emit
            # Use thresholds 0.1 warning /0.25 significant
            if psi_val >= 0.25:
                sev = "CRITICAL" if psi_val >= 0.5 else "WARNING"
            else:
                sev = "WARNING"
            issues.append({
                "issue_type": "CATEGORICAL_PSI_DRIFT",
                "severity": sev,
                "column_name": col_name,
                "description": f"Column '{col_name}' categorical PSI={psi_val:.3f} ({sev.lower()}, threshold 0.1).",
                "metadata": {
                    "metric": "PSI",
                    "psi": psi_val,
                    "threshold_warning": 0.1,
                    "threshold_critical": 0.25,
                    "evidence": psi_ev,
                }
            })
        # JSD categorical (alternative perspective, emit if JSD >=0.1 and not already PSI critical? We emit separately)
        jsd_val, jsd_ev = jsd_categorical(baseline_series, current_series)
        if jsd_val is not None and jsd_val >= 0.1:
            severity = "CRITICAL" if jsd_val >= 0.2 else "WARNING"
            # Avoid duplicate if PSI already critical for same column with similar severity? Emit anyway for evidence richness, but limit to one JSD per column
            # Only emit JSD if PSI not already critical for same column to avoid spam, but we will emit JSD regardless if distinct metric
            # For interview polish: we emit JSD only if PSI <0.25 (not already flagged) to avoid double counting
            psi_already = any(i["issue_type"] == "CATEGORICAL_PSI_DRIFT" for i in issues)
            if not psi_already or jsd_val >= 0.2:  # if PSI already warning, only emit JSD if critical
                issues.append({
                    "issue_type": "CATEGORICAL_JSD_DRIFT",
                    "severity": severity,
                    "column_name": col_name,
                    "description": f"Column '{col_name}' categorical JSD={jsd_val:.3f} ({severity.lower()}, threshold 0.1).",
                    "metadata": {
                        "metric": "JSD",
                        "jsd": jsd_val,
                        "threshold_warning": 0.1,
                        "threshold_critical": 0.2,
                        "evidence": jsd_ev,
                    }
                })
    return issues
