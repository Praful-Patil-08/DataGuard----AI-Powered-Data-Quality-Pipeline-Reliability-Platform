"""
Baselines — explicit, versioned, never silent.

Study: Marquez / OpenLineage run/dataset concepts, but baselines are dataset-centric snapshots.

Design:
- Logical dataset_name (e.g., orders) maps to physical dataset via _logical_name() prefix logic
- Only one is_active per logical dataset (enforced via deactivate on create/activate)
- Version increments per logical dataset
- Never silently updated after scan — must be explicitly created/activated via API
- Profiling snapshot derived from SchemaRecord columns (not duplicated JSON, but fingerprint+counts stored for quick compare)
- Quality snapshot from latest Scan quality_score if available
"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc
import models

def _logical_name(dataset_name: str) -> str:
    """Normalize to logical name: first token before _v/_bad/_drift or _."""
    if not dataset_name:
        return dataset_name
    lower = dataset_name.lower()
    for sep in ["_v", "_bad", "_drift"]:
        if sep in lower:
            return lower.split(sep)[0]
    # fallback first token
    return lower.split("_")[0] if "_" in lower else lower

def _logical_matches(contract_name: str, dataset_name: str) -> bool:
    """Reuse prefix matching logic from quality_contracts."""
    if not contract_name or not dataset_name:
        return False
    c = contract_name.lower()
    ds = dataset_name.lower()
    if ds == c:
        return True
    if ds.startswith(c + "_") or ds.startswith(c + ".") or ds.startswith(c + "-"):
        return True
    # logical prefix
    if _logical_name(ds) == c:
        return True
    if _logical_name(c) == _logical_name(ds):
        return True
    return False

def get_active_baseline(db: Session, dataset_name: str) -> Optional[models.Baseline]:
    logical = _logical_name(dataset_name)
    # Try exact logical match active first
    b = db.query(models.Baseline).filter(
        models.Baseline.dataset_name == logical,
        models.Baseline.is_active == True
    ).order_by(desc(models.Baseline.created_at)).first()
    if b:
        return b
    # Try prefix matches with is_active
    all_active = db.query(models.Baseline).filter(models.Baseline.is_active == True).all()
    for cand in all_active:
        if _logical_matches(cand.dataset_name, dataset_name):
            return cand
    # Fallback: any baseline for that logical name even if not active but latest
    b = db.query(models.Baseline).filter(models.Baseline.dataset_name == logical).order_by(desc(models.Baseline.created_at)).first()
    return b

def list_baselines(db: Session, dataset_name: Optional[str] = None, include_inactive: bool = True) -> List[models.Baseline]:
    q = db.query(models.Baseline).order_by(desc(models.Baseline.created_at))
    if dataset_name:
        logical = _logical_name(dataset_name)
        # Filter by logical match
        all_b = q.all()
        matched = [b for b in all_b if _logical_matches(b.dataset_name, dataset_name) or b.dataset_name == logical]
        if not include_inactive:
            matched = [b for b in matched if b.is_active]
        return matched
    if not include_inactive:
        q = q.filter(models.Baseline.is_active == True)
    return q.all()

def create_baseline(
    db: Session,
    dataset_name: str,
    baseline_dataset_id: int,
    description: Optional[str] = None,
    created_by: str = "system",
    set_active: bool = True,
) -> models.Baseline:
    # Validate dataset exists
    ds = db.query(models.Dataset).filter(models.Dataset.id == baseline_dataset_id).first()
    if not ds:
        raise ValueError(f"Dataset {baseline_dataset_id} not found")
    # Resolve schema
    schema = db.query(models.SchemaRecord).filter(
        models.SchemaRecord.dataset_id == baseline_dataset_id
    ).order_by(desc(models.SchemaRecord.created_at)).first()
    if not schema:
        raise ValueError(f"No schema found for dataset {baseline_dataset_id}")
    logical = _logical_name(dataset_name or ds.name)
    # Determine version: max version for this logical +1
    max_v = db.query(models.Baseline).filter(models.Baseline.dataset_name == logical).order_by(desc(models.Baseline.version)).first()
    version = (max_v.version + 1) if max_v else 1
    # Snapshot quality_score from latest scan for this dataset if exists
    latest_scan = db.query(models.Scan).filter(models.Scan.dataset_id == baseline_dataset_id).order_by(desc(models.Scan.completed_at)).first()
    quality_score = float(latest_scan.quality_score) if latest_scan and latest_scan.quality_score is not None else None
    # Create
    baseline = models.Baseline(
        dataset_name=logical,
        baseline_dataset_id=baseline_dataset_id,
        baseline_schema_id=schema.id,
        fingerprint=schema.fingerprint,
        row_count=ds.row_count,
        column_count=ds.column_count,
        quality_score=quality_score,
        version=version,
        is_active=set_active,
        description=description,
        created_by=created_by,
    )
    if set_active:
        # Deactivate others for same logical
        db.query(models.Baseline).filter(
            models.Baseline.dataset_name == logical,
            models.Baseline.is_active == True
        ).update({models.Baseline.is_active: False})
    db.add(baseline)
    db.commit()
    db.refresh(baseline)
    return baseline

def activate_baseline(db: Session, baseline_id: int) -> Optional[models.Baseline]:
    b = db.query(models.Baseline).filter(models.Baseline.id == baseline_id).first()
    if not b:
        return None
    # Deactivate others for same logical
    db.query(models.Baseline).filter(
        models.Baseline.dataset_name == b.dataset_name,
        models.Baseline.is_active == True
    ).update({models.Baseline.is_active: False})
    b.is_active = True
    db.commit()
    db.refresh(b)
    return b

def deactivate_baseline(db: Session, baseline_id: int) -> Optional[models.Baseline]:
    b = db.query(models.Baseline).filter(models.Baseline.id == baseline_id).first()
    if not b:
        return None
    b.is_active = False
    db.commit()
    db.refresh(b)
    return b

def delete_baseline(db: Session, baseline_id: int) -> bool:
    b = db.query(models.Baseline).filter(models.Baseline.id == baseline_id).first()
    if not b:
        return False
    db.delete(b)
    db.commit()
    return True

def get_baseline_comparison(
    db: Session,
    baseline: models.Baseline,
    candidate_dataset_id: int,
) -> Dict[str, Any]:
    """Helper to return baseline vs candidate comparison metadata."""
    candidate_ds = db.query(models.Dataset).filter(models.Dataset.id == candidate_dataset_id).first()
    if not candidate_ds:
        raise ValueError("Candidate dataset not found")
    candidate_schema = db.query(models.SchemaRecord).filter(
        models.SchemaRecord.dataset_id == candidate_dataset_id
    ).order_by(desc(models.SchemaRecord.created_at)).first()
    return {
        "baseline": {
            "id": baseline.id,
            "dataset_name": baseline.dataset_name,
            "baseline_dataset_id": baseline.baseline_dataset_id,
            "fingerprint": baseline.fingerprint,
            "row_count": baseline.row_count,
            "column_count": baseline.column_count,
            "quality_score": baseline.quality_score,
            "version": baseline.version,
            "is_active": baseline.is_active,
            "created_at": baseline.created_at.isoformat() if baseline.created_at else None,
        },
        "candidate": {
            "dataset_id": candidate_ds.id,
            "dataset_name": candidate_ds.name,
            "row_count": candidate_ds.row_count,
            "column_count": candidate_ds.column_count,
            "fingerprint": candidate_schema.fingerprint if candidate_schema else None,
        }
    }
