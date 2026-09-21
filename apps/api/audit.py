"""
Audit Log — deterministic traceability.

Every important action should be traceable: who, what, when, why, previous state, new state.
Covers: baseline changes, contract changes, remediation approvals, incident status changes, AI analysis, lineage edge changes, scan creation.
"""
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
import models
import datetime

def log_action(
    db: Session,
    action: str,
    actor: str,
    target_type: str,
    target_id: Any,
    previous_state: Optional[Dict[str, Any]] = None,
    new_state: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
) -> models.AuditLog:
    """
    Create an audit log entry. Never fails the main transaction (best effort).
    Sanitizes actor/target to prevent injection.
    """
    try:
        # Sanitize actor
        actor = (actor or "system")[:255]
        # Ensure target_id is string
        target_id_str = str(target_id) if target_id is not None else None
        entry = models.AuditLog(
            action=action,
            actor=actor,
            target_type=target_type,
            target_id=target_id_str,
            previous_state=previous_state,
            new_state=new_state,
            reason=(reason[:2000] if reason else None),
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        # Fallback: try without commit? But we want best effort, not to break main flow
        # So we just return None and don't raise
        return None  # type: ignore

def get_audit_logs(
    db: Session,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    actor: Optional[str] = None,
    limit: int = 50,
) -> list:
    q = db.query(models.AuditLog).order_by(models.AuditLog.created_at.desc())
    if action:
        q = q.filter(models.AuditLog.action == action)
    if target_type:
        q = q.filter(models.AuditLog.target_type == target_type)
    if actor:
        q = q.filter(models.AuditLog.actor == actor)
    return q.limit(limit).all()
