"""
Quality Contracts — declarative expectations (SodaCL / Great Expectations inspired).

Design study:
- Soda Core: checks.yml declares `missing_percent(col) < 1%`, `duplicate_percent < 0`, `invalid_percent(col) < 0.5%` per dataset
- Great Expectations: ExpectationSuite per dataset with typed Expectations + kwargs + meta
- DataGuard native: `QualityContract` table (versioned, enabled flag) + deterministic evaluator

Concepts reimplemented natively:
- Contract is *expectation* (dataset.column + contract_type + threshold + params + severity)
- Evaluation is *deterministic* (pandas only, no LLM) and returns structured breach with evidence
- Versioning: `version` increments on update, `updated_at` tracks recency, history reconstructable via scanIssues (breaches are Issues)
- Explainability: every breach contains expected threshold, actual value, evidence, affected column

Contract types (MVP):
- completeness  — must not be null >= threshold (e.g., customer_id 0.99)
- uniqueness    — must be unique >= threshold (e.g., order_id 1.0)
- range         — numeric must be within [min,max] >= threshold validity (e.g., amount positive)
- regex         — string must match pattern >= threshold
- row_count     — table must have row_count within [min,max] (table-level, column_name None)

Threshold semantics: all thresholds are 0.0-1.0 validity ratio (>= threshold passes). For strict 100% use 1.0.
"""
import re
from typing import List, Dict, Any, Optional

import pandas as pd
from sqlalchemy.orm import Session

import models


VALID_CONTRACT_TYPES = {"completeness", "uniqueness", "range", "regex", "row_count", "not_null", "unique"}
# Aliases normalized
TYPE_ALIASES = {"not_null": "completeness", "unique": "uniqueness"}

def _normalize_type(ct: str) -> str:
    ct = ct.lower().strip()
    return TYPE_ALIASES.get(ct, ct)

def _contract_matches(dataset_name: str, contract_dataset_name: str) -> bool:
    """Soda-like dataset matching: logical name with prefix fallback (orders matches orders_v1)."""
    if not dataset_name or not contract_dataset_name:
        return False
    ds = dataset_name.lower()
    c = contract_dataset_name.lower()
    if ds == c:
        return True
    # exact prefix with separator
    if ds.startswith(c + "_") or ds.startswith(c + ".") or ds.startswith(c + "-"):
        return True
    # also handle contract "orders" matching "orders" dataset via split
    # dataset prefix before _v/_bad/_drift
    for sep in ["_v", "_bad", "_drift"]:
        if sep in ds:
            prefix = ds.split(sep)[0]
            if prefix == c:
                return True
    # first token fallback (orders_v1 -> orders)
    if ds.split("_")[0] == c:
        return True
    # reverse: contract "orders_v1" should not match "orders_v2", so no reverse
    return False

def get_contracts_for_dataset(db: Session, dataset_name: str, only_enabled: bool = True) -> List[models.QualityContract]:
    q = db.query(models.QualityContract)
    if only_enabled:
        q = q.filter(models.QualityContract.enabled == True)
    all_contracts = q.all()
    matched = [c for c in all_contracts if _contract_matches(dataset_name, c.dataset_name)]
    return matched

def evaluate_contracts(
    df: pd.DataFrame,
    dataset_name: str,
    contracts: List[models.QualityContract],
) -> List[Dict[str, Any]]:
    """
    Deterministically evaluate contracts against a DataFrame.
    Returns list of breach issue dicts (compatible with main.py Issue creation).
    Each breach is an Issue with issue_type = CONTRACT_BREACH_<TYPE>.
    """
    issues: List[Dict[str, Any]] = []
    total_rows = len(df)
    if total_rows == 0:
        # No rows: completeness contracts technically breach if threshold >0, but we emit EMPTY_DATASET already
        # For row_count contracts, evaluate separately
        for c in contracts:
            if _normalize_type(c.contract_type) == "row_count":
                # Evaluate row_count even on empty?
                breach = _evaluate_row_count(df, c, total_rows)
                if breach:
                    issues.append(breach)
        return issues

    for c in contracts:
        ct = _normalize_type(c.contract_type)
        col = c.column_name
        threshold = c.threshold
        params = c.params or {}
        severity = c.severity or "WARNING"
        # Route to evaluator
        breach = None
        try:
            if ct == "completeness":
                breach = _evaluate_completeness(df, c, total_rows, col, threshold, params, severity)
            elif ct == "uniqueness":
                breach = _evaluate_uniqueness(df, c, total_rows, col, threshold, params, severity)
            elif ct == "range":
                breach = _evaluate_range(df, c, total_rows, col, threshold, params, severity)
            elif ct == "regex":
                breach = _evaluate_regex(df, c, total_rows, col, threshold, params, severity)
            elif ct == "row_count":
                breach = _evaluate_row_count(df, c, total_rows)
                # ensure severity from contract if not already set
                if breach and c.severity:
                    breach["severity"] = c.severity
            else:
                # Unknown type -> emit warning issue for visibility
                breach = {
                    "issue_type": "CONTRACT_UNKNOWN_TYPE",
                    "severity": "WARNING",
                    "column_name": col,
                    "description": f"Contract {c.id} has unknown type '{c.contract_type}' for '{col}'.",
                    "metadata": {"contract_id": c.id, "contract_type": c.contract_type, "dataset": c.dataset_name},
                }
        except Exception as e:
            breach = {
                "issue_type": "CONTRACT_EVALUATION_ERROR",
                "severity": "WARNING",
                "column_name": col,
                "description": f"Contract {c.id} evaluation failed: {str(e)[:100]}",
                "metadata": {"contract_id": c.id, "error": str(e)[:300]},
            }
        if breach:
            issues.append(breach)
    return issues

def _evaluate_completeness(df: pd.DataFrame, contract: models.QualityContract, total_rows: int, column: Optional[str], threshold: Optional[float], params: Dict[str, Any], severity: str) -> Optional[Dict[str, Any]]:
    if not column or column not in df.columns:
        return {
            "issue_type": "CONTRACT_BREACH_COMPLETENESS",
            "severity": severity,
            "column_name": column,
            "description": f"Contract breach: column '{column}' not found for completeness check (dataset missing column).",
            "metadata": {"contract_id": contract.id, "dataset": contract.dataset_name, "column": column, "expected_threshold": threshold, "actual": None, "reason": "column_not_found"},
        }
    null_count = int(df[column].isna().sum())
    completeness = 1.0 - (null_count / total_rows) if total_rows else 0.0
    # Threshold is minimum completeness required (e.g., 0.99 means at most 1% null)
    exp = threshold if threshold is not None else params.get("threshold", 0.99)
    if completeness < exp:
        completeness_pct = round(completeness * 100, 2)
        expected_pct = round(exp * 100, 2)
        null_pct = round((null_count / total_rows) * 100, 2)
        return {
            "issue_type": "CONTRACT_BREACH_COMPLETENESS",
            "severity": severity,
            "column_name": column,
            "description": f"Completeness breach on '{column}': {completeness_pct}% complete ({null_pct}% null) < expected {expected_pct}% (contract v{contract.version}).",
            "metadata": {
                "contract_id": contract.id,
                "contract_type": "completeness",
                "dataset": contract.dataset_name,
                "column": column,
                "threshold": exp,
                "expected_completeness": exp,
                "actual_completeness": round(completeness, 4),
                "null_count": null_count,
                "null_pct": null_pct,
                "total_rows": total_rows,
                "version": contract.version,
            },
        }
    return None

def _evaluate_uniqueness(df: pd.DataFrame, contract: models.QualityContract, total_rows: int, column: Optional[str], threshold: Optional[float], params: Dict[str, Any], severity: str) -> Optional[Dict[str, Any]]:
    if not column or column not in df.columns:
        return {
            "issue_type": "CONTRACT_BREACH_UNIQUENESS",
            "severity": severity,
            "column_name": column,
            "description": f"Contract breach: column '{column}' not found for uniqueness check.",
            "metadata": {"contract_id": contract.id, "column": column, "expected_threshold": threshold, "actual": None, "reason": "column_not_found"},
        }
    unique_count = int(df[column].nunique(dropna=True))
    # For uniqueness, we consider nulls as not unique? Use unique_count / total rows (or non-null)
    uniqueness = unique_count / total_rows if total_rows else 0.0
    # Alternative: unique_ratio as in scanner (unique_count / total). For strict PK, expect 1.0.
    exp = threshold if threshold is not None else params.get("threshold", 1.0)
    if uniqueness < exp:
        uniq_pct = round(uniqueness * 100, 2)
        expected_pct = round(exp * 100, 2)
        dup_count = total_rows - unique_count
        # More accurate duplicate count via duplicated (excluding nulls?)
        try:
            dup_count2 = int(df[column].dropna().duplicated().sum())
        except:
            dup_count2 = dup_count
        return {
            "issue_type": "CONTRACT_BREACH_UNIQUENESS",
            "severity": severity,
            "column_name": column,
            "description": f"Uniqueness breach on '{column}': {uniq_pct}% unique ({dup_count2} duplicates) < expected {expected_pct}% (contract v{contract.version}).",
            "metadata": {
                "contract_id": contract.id,
                "contract_type": "uniqueness",
                "dataset": contract.dataset_name,
                "column": column,
                "threshold": exp,
                "expected_uniqueness": exp,
                "actual_uniqueness": round(uniqueness, 4),
                "unique_count": unique_count,
                "duplicate_count": dup_count2,
                "total_rows": total_rows,
                "version": contract.version,
            },
        }
    return None

def _evaluate_range(df: pd.DataFrame, contract: models.QualityContract, total_rows: int, column: Optional[str], threshold: Optional[float], params: Dict[str, Any], severity: str) -> Optional[Dict[str, Any]]:
    if not column or column not in df.columns:
        return {
            "issue_type": "CONTRACT_BREACH_RANGE",
            "severity": severity,
            "column_name": column,
            "description": f"Contract breach: column '{column}' not found for range check.",
            "metadata": {"contract_id": contract.id, "column": column, "reason": "column_not_found"},
        }
    # Params must contain min/max (could be one side)
    min_val = params.get("min")
    max_val = params.get("max")
    if min_val is None and max_val is None:
        # Use threshold as min? fallback
        return {
            "issue_type": "CONTRACT_BREACH_RANGE",
            "severity": "WARNING",
            "column_name": column,
            "description": f"Contract {contract.id} range missing min/max params.",
            "metadata": {"contract_id": contract.id, "params": params},
        }
    series = pd.to_numeric(df[column], errors="coerce")
    valid_mask = series.notna()
    if valid_mask.sum() == 0:
        return None  # no numeric data, not a breach (or could be warning)
    # Determine validity mask
    valid_range = pd.Series([True] * len(series))
    if min_val is not None:
        valid_range = valid_range & (series >= min_val)
    if max_val is not None:
        valid_range = valid_range & (series <= max_val)
    # Only consider non-null numeric values for validity ratio? Use total rows for strictness
    # Soda style: invalid_percent = invalid / total
    invalid_count = int((~valid_range & valid_mask).sum())
    # For rows with null, not counted as invalid for range (completeness handles nulls)
    total_validatable = int(valid_mask.sum())
    validity = (total_validatable - invalid_count) / total_validatable if total_validatable else 1.0
    exp = threshold if threshold is not None else params.get("threshold", 1.0)
    # If threshold is None and params threshold not set, default to 1.0 for strict positive check example
    # For "must be positive >=99.5%" -> min=0, threshold=0.995
    if validity < exp:
        validity_pct = round(validity * 100, 2)
        expected_pct = round(exp * 100, 2)
        # sample invalid values
        invalid_samples = series[~valid_range & valid_mask].head(3).tolist()
        desc_min_max = f"[{min_val}, {max_val}]" if min_val is not None and max_val is not None else (f">= {min_val}" if min_val is not None else f"<= {max_val}")
        return {
            "issue_type": "CONTRACT_BREACH_RANGE",
            "severity": severity,
            "column_name": column,
            "description": f"Range breach on '{column}': {validity_pct}% valid within {desc_min_max} < expected {expected_pct}% ({invalid_count} invalid, samples {invalid_samples}) (contract v{contract.version}).",
            "metadata": {
                "contract_id": contract.id,
                "contract_type": "range",
                "dataset": contract.dataset_name,
                "column": column,
                "threshold": exp,
                "expected_validity": exp,
                "actual_validity": round(validity, 4),
                "min": min_val,
                "max": max_val,
                "invalid_count": invalid_count,
                "invalid_samples": invalid_samples,
                "total_validatable": total_validatable,
                "version": contract.version,
            },
        }
    return None

def _evaluate_regex(df: pd.DataFrame, contract: models.QualityContract, total_rows: int, column: Optional[str], threshold: Optional[float], params: Dict[str, Any], severity: str) -> Optional[Dict[str, Any]]:
    if not column or column not in df.columns:
        return {
            "issue_type": "CONTRACT_BREACH_REGEX",
            "severity": severity,
            "column_name": column,
            "description": f"Contract breach: column '{column}' not found for regex check.",
            "metadata": {"contract_id": contract.id, "column": column, "reason": "column_not_found"},
        }
    pattern = params.get("pattern") or params.get("regex")
    if not pattern:
        return {
            "issue_type": "CONTRACT_BREACH_REGEX",
            "severity": "WARNING",
            "column_name": column,
            "description": f"Contract {contract.id} regex missing pattern param.",
            "metadata": {"contract_id": contract.id, "params": params},
        }
    series = df[column].dropna().astype(str)
    if len(series) == 0:
        return None
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return {
            "issue_type": "CONTRACT_BREACH_REGEX",
            "severity": "WARNING",
            "column_name": column,
            "description": f"Contract {contract.id} invalid regex '{pattern}': {str(e)[:60]}",
            "metadata": {"contract_id": contract.id, "pattern": pattern, "error": str(e)},
        }
    matches = sum(1 for v in series if regex.search(v))
    validity = matches / len(series) if len(series) else 1.0
    exp = threshold if threshold is not None else params.get("threshold", 1.0)
    if validity < exp:
        validity_pct = round(validity * 100, 2)
        expected_pct = round(exp * 100, 2)
        invalid_samples = [v for v in series if not regex.search(v)][:3]
        return {
            "issue_type": "CONTRACT_BREACH_REGEX",
            "severity": severity,
            "column_name": column,
            "description": f"Regex breach on '{column}': {validity_pct}% match '{pattern}' < expected {expected_pct}% ({len(series)-matches} invalid, samples {invalid_samples}) (contract v{contract.version}).",
            "metadata": {
                "contract_id": contract.id,
                "contract_type": "regex",
                "dataset": contract.dataset_name,
                "column": column,
                "threshold": exp,
                "expected_validity": exp,
                "actual_validity": round(validity, 4),
                "pattern": pattern,
                "mismatch_count": len(series) - matches,
                "mismatch_samples": invalid_samples,
                "version": contract.version,
            },
        }
    return None

def _evaluate_row_count(df: pd.DataFrame, contract: models.QualityContract, total_rows: int) -> Optional[Dict[str, Any]]:
    params = contract.params or {}
    min_rc = params.get("min") or params.get("min_rows")
    max_rc = params.get("max") or params.get("max_rows")
    severity = contract.severity or "WARNING"
    if min_rc is None and max_rc is None:
        return None
    breach = False
    reason = ""
    if min_rc is not None and total_rows < min_rc:
        breach = True
        reason = f"row count {total_rows} < min {min_rc}"
    if max_rc is not None and total_rows > max_rc:
        breach = True
        reason = f"row count {total_rows} > max {max_rc}"
    if breach:
        return {
            "issue_type": "CONTRACT_BREACH_ROW_COUNT",
            "severity": severity,
            "column_name": None,
            "description": f"Row count breach: {reason} (contract v{contract.version} for '{contract.dataset_name}').",
            "metadata": {
                "contract_id": contract.id,
                "contract_type": "row_count",
                "dataset": contract.dataset_name,
                "actual_row_count": total_rows,
                "min": min_rc,
                "max": max_rc,
                "version": contract.version,
            },
        }
    return None

# CRUD helpers
def create_contract(db: Session, data: Dict[str, Any]) -> models.QualityContract:
    ct = _normalize_type(data["contract_type"])
    if ct not in VALID_CONTRACT_TYPES:
        # allow alias normalized already; if still invalid, raise
        if ct not in {"completeness","uniqueness","range","regex","row_count"}:
            raise ValueError(f"Invalid contract_type '{data['contract_type']}'. Valid: {VALID_CONTRACT_TYPES}")
    contract = models.QualityContract(
        dataset_name=data["dataset_name"],
        column_name=data.get("column_name"),
        contract_type=ct,
        threshold=data.get("threshold"),
        params=data.get("params") or {},
        severity=data.get("severity") or "WARNING",
        description=data.get("description"),
        enabled=data.get("enabled", True),
        version=1,
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract

def update_contract(db: Session, contract_id: int, data: Dict[str, Any]) -> Optional[models.QualityContract]:
    c = db.query(models.QualityContract).filter(models.QualityContract.id == contract_id).first()
    if not c:
        return None
    # update fields if provided
    for field in ["dataset_name","column_name","threshold","params","severity","description","enabled"]:
        if field in data and data[field] is not None:
            if field == "threshold" and data[field] is not None:
                setattr(c, field, float(data[field]))
            else:
                setattr(c, field, data[field])
    if "contract_type" in data and data["contract_type"]:
        c.contract_type = _normalize_type(data["contract_type"])
    c.version = (c.version or 1) + 1
    # updated_at auto via onupdate but set explicitly for sqlite
    import datetime
    c.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(c)
    return c

def delete_contract(db: Session, contract_id: int) -> bool:
    c = db.query(models.QualityContract).filter(models.QualityContract.id == contract_id).first()
    if not c:
        return False
    db.delete(c)
    db.commit()
    return True
