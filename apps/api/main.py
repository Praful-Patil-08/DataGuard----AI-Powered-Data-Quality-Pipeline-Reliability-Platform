import os
import datetime
from typing import List, Optional, Any
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import engine, Base, get_db, run_migrations
import models
import schemas
from scanner import parse_dataset_content, profile_dataframe
from drift import detect_schema_drift, generate_incident_summary, assess_gate
from quality import run_quality_checks
from quality_score import compute_quality_score
from lineage import get_downstream_impact, DEFAULT_LINEAGE_MAP, get_lineage_config, is_demo_lineage, CONFIG_PATH
import lineage_graph
from ai import run_ai_analyst
import quality_contracts as qc_manager
import baselines as baseline_manager
import incidents as incident_manager
import json as _json
from storage_backend import save_file, load_file, STORAGE_DIR

# Create all database tables + lightweight migrations on startup
models.Base.metadata.create_all(bind=engine)
try:
    run_migrations()
except Exception:
    pass

app = FastAPI(
    title="DataGuard API",
    description="Deterministic & AI-Assisted Data Reliability Platform",
    version="1.0.0"
)

# Configure CORS
origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Health & Statistics -----------------
@app.get("/api/health", response_model=schemas.HealthResponse)
def health_check(db: Session = Depends(get_db)):
    # Test DB connectivity
    try:
        db.execute(models.Dataset.__table__.select().limit(1))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    return {
        "status": "healthy",
        "database": db_status,
        "timestamp": datetime.datetime.now(datetime.timezone.utc)
    }

@app.get("/api/dashboard/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    datasets_count = db.query(models.Dataset).count()
    scans = db.query(models.Scan).all()
    total_scans = len(scans)
    healthy_scans = sum(1 for s in scans if s.critical_count == 0 and s.warning_count == 0)
    warning_scans = sum(1 for s in scans if s.warning_count > 0 and s.critical_count == 0)
    critical_scans = sum(1 for s in scans if s.critical_count > 0)

    pending_remediations = db.query(models.Remediation).filter(models.Remediation.status == "PENDING").count()

    return {
        "datasets_count": datasets_count,
        "total_scans": total_scans,
        "healthy_count": healthy_scans,
        "warning_count": warning_scans,
        "critical_count": critical_scans,
        "pending_remediations": pending_remediations
    }

# ----------------- Datasets -----------------
@app.post("/api/datasets/upload", response_model=schemas.DatasetUploadResponse)
async def upload_dataset(
    file: UploadFile = File(...),
    dataset_name: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    
    filename = file.filename
    ext = filename.lower().split(".")[-1]
    if ext not in ["csv", "json"]:
        raise HTTPException(status_code=400, detail="Only CSV and JSON files are supported.")

    content = await file.read()
    if len(content) > 100 * 1024 * 1024: # 100MB limit — handles Olist geolocation 58MB real data
        raise HTTPException(status_code=400, detail="File exceeds maximum size limit (100MB).")
    # Security: basic CSV/JSON header validation
    if ext == "csv" and content[:3] == b"\xef\xbb\xbf":
        content = content[3:]  # strip BOM
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file.")

    try:
        df = parse_dataset_content(content, filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    row_count = len(df)
    column_count = len(df.columns)
    name = dataset_name or filename.rsplit(".", 1)[0]

    # Create dataset record
    dataset = models.Dataset(
        name=name,
        filename=filename,
        file_type=ext,
        row_count=row_count,
        column_count=column_count,
        created_at=datetime.datetime.now(datetime.timezone.utc)
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    # Persist raw file for quality checks during scan (abstraction supports S3)
    try:
        save_file(dataset.id, filename, content)
    except Exception:
        pass  # Non-critical: scan will fallback to metadata-only checks

    # Compute schema profile & fingerprint
    column_profiles, fingerprint = profile_dataframe(df)

    schema_record = models.SchemaRecord(
        dataset_id=dataset.id,
        fingerprint=fingerprint,
        created_at=datetime.datetime.now(datetime.timezone.utc)
    )
    db.add(schema_record)
    db.commit()
    db.refresh(schema_record)

    # Save columns - enhanced with Watchtower profiling
    for cp in column_profiles:
        sc = models.SchemaColumn(
            schema_id=schema_record.id,
            column_name=cp["column_name"],
            data_type=cp["data_type"],
            nullable=cp["nullable"],
            unique_count=cp["unique_count"],
            null_count=cp["null_count"],
            sample_values=cp["sample_values"],
            null_rate=cp.get("null_rate", 0.0),
            unique_ratio=cp.get("unique_ratio", 0.0),
            min_value=cp.get("min_value"),
            max_value=cp.get("max_value"),
            mean=cp.get("mean"),
            median=cp.get("median"),
            p05=cp.get("p05"),
            p95=cp.get("p95"),
            outlier_count=cp.get("outlier_count", 0),
            outlier_rate=cp.get("outlier_rate", 0.0),
            top_values=cp.get("top_values", []),
        )
        db.add(sc)
    db.commit()

    return {
        "dataset_id": dataset.id,
        "filename": filename,
        "row_count": row_count,
        "column_count": column_count
    }

@app.get("/api/datasets", response_model=List[schemas.DatasetResponse])
def list_datasets(db: Session = Depends(get_db)):
    return db.query(models.Dataset).order_by(desc(models.Dataset.created_at)).all()

@app.get("/api/datasets/{dataset_id}", response_model=schemas.DatasetResponse)
def get_dataset(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return ds

@app.get("/api/datasets/{dataset_id}/schema", response_model=schemas.SchemaResponse)
def get_dataset_schema(dataset_id: int, db: Session = Depends(get_db)):
    schema = db.query(models.SchemaRecord).filter(
        models.SchemaRecord.dataset_id == dataset_id
    ).order_by(desc(models.SchemaRecord.created_at)).first()
    if not schema:
        raise HTTPException(status_code=404, detail="No schema found for dataset")
    return schema

@app.get("/api/datasets/{dataset_id}/schemas", response_model=List[schemas.SchemaResponse])
def list_dataset_schemas(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    schemas = db.query(models.SchemaRecord).filter(models.SchemaRecord.dataset_id == dataset_id).order_by(desc(models.SchemaRecord.created_at)).all()
    return schemas

@app.get("/api/datasets/{dataset_id}/schema/history")
def get_schema_history(dataset_id: int, db: Session = Depends(get_db)):
    """
    Historical schema versions — per logical dataset (prefix) and per physical dataset.
    Returns both physical schemas for this dataset and logical evolution across prefix.
    """
    ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    # Physical schemas for this dataset
    physical = db.query(models.SchemaRecord).filter(models.SchemaRecord.dataset_id == dataset_id).order_by(models.SchemaRecord.created_at.asc()).all()
    # Logical: find datasets with same prefix
    prefix = ds.name.split("_v")[0].split("_bad")[0].split("_drift")[0] if ds.name else ds.name
    # Fallback to first token
    if not prefix:
        prefix = ds.name
    else:
        # Use first token if prefix too long? Keep as is
        pass
    logical_datasets = db.query(models.Dataset).filter(models.Dataset.name.like(f"{prefix}%")).order_by(models.Dataset.created_at.asc()).all()
    logical = []
    for lds in logical_datasets:
        sch = db.query(models.SchemaRecord).filter(models.SchemaRecord.dataset_id == lds.id).order_by(desc(models.SchemaRecord.created_at)).first()
        if sch:
            logical.append({
                "dataset_id": lds.id,
                "dataset_name": lds.name,
                "schema_id": sch.id,
                "fingerprint": sch.fingerprint,
                "created_at": sch.created_at.isoformat() if sch.created_at else None,
                "column_count": len(sch.columns),
                "columns": [{"column_name": c.column_name, "data_type": c.data_type, "nullable": c.nullable} for c in sch.columns],
            })
    return {
        "dataset_id": dataset_id,
        "dataset_name": ds.name,
        "physical_history": [{"id": s.id, "fingerprint": s.fingerprint, "created_at": s.created_at.isoformat() if s.created_at else None} for s in physical],
        "logical_evolution": logical,
    }

@app.get("/api/datasets/{dataset_id}/schema/compare")
def compare_schemas(dataset_id: int, baseline_dataset_id: int, db: Session = Depends(get_db)):
    """
    Compare schemas deterministically — returns drift issues including rename candidates with evidence.
    """
    ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    base_ds = db.query(models.Dataset).filter(models.Dataset.id == baseline_dataset_id).first()
    if not ds or not base_ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    curr_schema = db.query(models.SchemaRecord).filter(models.SchemaRecord.dataset_id == dataset_id).order_by(desc(models.SchemaRecord.created_at)).first()
    base_schema = db.query(models.SchemaRecord).filter(models.SchemaRecord.dataset_id == baseline_dataset_id).order_by(desc(models.SchemaRecord.created_at)).first()
    if not curr_schema or not base_schema:
        raise HTTPException(status_code=404, detail="Schema not found for one of the datasets")
    curr_cols = [{
        "column_name": c.column_name,
        "data_type": c.data_type,
        "nullable": c.nullable,
        "null_count": c.null_count,
        "unique_count": c.unique_count,
        "null_rate": c.null_rate if c.null_rate is not None else 0.0,
        "unique_ratio": c.unique_ratio if c.unique_ratio is not None else 0.0,
        "mean": c.mean, "median": c.median, "min_value": c.min_value, "max_value": c.max_value,
        "p05": c.p05, "p95": c.p95, "outlier_count": c.outlier_count or 0, "outlier_rate": c.outlier_rate if c.outlier_rate is not None else 0.0,
        "top_values": c.top_values or [],
    } for c in curr_schema.columns]
    base_cols = [{
        "column_name": c.column_name,
        "data_type": c.data_type,
        "nullable": c.nullable,
        "null_count": c.null_count,
        "unique_count": c.unique_count,
        "null_rate": c.null_rate if c.null_rate is not None else 0.0,
        "unique_ratio": c.unique_ratio if c.unique_ratio is not None else 0.0,
        "mean": c.mean, "median": c.median, "min_value": c.min_value, "max_value": c.max_value,
        "p05": c.p05, "p95": c.p95, "outlier_count": c.outlier_count or 0, "outlier_rate": c.outlier_rate if c.outlier_rate is not None else 0.0,
        "top_values": c.top_values or [],
    } for c in base_schema.columns]
    # Try to load DataFrames for statistical drift (PSI/KS/JSD)
    df_baseline = None
    df_current = None
    def _load_df(ds):
        try:
            exact_path = os.path.join(STORAGE_DIR, f"{ds.id}_{ds.filename}")
            stored_path = exact_path if os.path.exists(exact_path) else None
            if not stored_path:
                for fname in os.listdir(STORAGE_DIR):
                    if fname.startswith(f"{ds.id}_"):
                        stored_path = os.path.join(STORAGE_DIR, fname)
                        break
            if not stored_path and ds.name in ("orders_v1","orders_v2_schema_drift","orders_bad_quality","customers_v1","products_v1"):
                for p in [os.path.abspath(os.path.join(STORAGE_DIR, "../../sample-data", f"{ds.name}.csv")),
                          os.path.abspath(os.path.join(os.path.dirname(__file__), "../../sample-data", f"{ds.name}.csv"))]:
                    if os.path.exists(p):
                        stored_path = p
                        break
            if stored_path and os.path.exists(stored_path):
                with open(stored_path, "rb") as fh:
                    content = fh.read()
                return parse_dataset_content(content, ds.filename or stored_path)
        except Exception:
            pass
        return None
    try:
        df_baseline = _load_df(base_ds)
        df_current = _load_df(ds)
    except Exception:
        pass
    drift_issues = detect_schema_drift(base_cols, curr_cols, baseline_row_count=base_ds.row_count, current_row_count=ds.row_count, baseline_df=df_baseline, current_df=df_current)
    # Split rename candidates and statistical drifts
    rename_candidates = [i for i in drift_issues if i["issue_type"] == "COLUMN_RENAMED_CANDIDATE"]
    statistical = [i for i in drift_issues if i["issue_type"] in ("NUMERIC_PSI_DRIFT","NUMERIC_KS_DRIFT","CATEGORICAL_PSI_DRIFT","CATEGORICAL_JSD_DRIFT")]
    return {
        "baseline_dataset_id": baseline_dataset_id,
        "baseline_dataset_name": base_ds.name,
        "candidate_dataset_id": dataset_id,
        "candidate_dataset_name": ds.name,
        "drift_issues": drift_issues,
        "rename_candidates": rename_candidates,
        "statistical_drifts": statistical,
        "summary": f"{len(drift_issues)} drift issues, {len(rename_candidates)} rename candidates, {len(statistical)} statistical drifts"
    }

# ----------------- Scanning & Deterministic Engines -----------------
@app.post("/api/datasets/{dataset_id}/scan", response_model=schemas.ScanResponse)
def scan_dataset(
    dataset_id: int,
    baseline_dataset_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Fetch current schema
    current_schema = db.query(models.SchemaRecord).filter(
        models.SchemaRecord.dataset_id == dataset_id
    ).order_by(desc(models.SchemaRecord.created_at)).first()
    if not current_schema:
        raise HTTPException(status_code=400, detail="Dataset has not been profiled yet.")

    curr_cols = [{
        "column_name": c.column_name,
        "data_type": c.data_type,
        "nullable": c.nullable,
        "null_count": c.null_count,
        "unique_count": c.unique_count,
        "null_rate": c.null_rate if c.null_rate is not None else 0.0,
        "unique_ratio": c.unique_ratio if c.unique_ratio is not None else 0.0,
        "mean": c.mean,
        "median": c.median,
        "min_value": c.min_value,
        "max_value": c.max_value,
        "p05": c.p05,
        "p95": c.p95,
        "outlier_count": c.outlier_count or 0,
        "outlier_rate": c.outlier_rate if c.outlier_rate is not None else 0.0,
        "top_values": c.top_values or [],
    } for c in current_schema.columns]

    # Look for baseline schema — explicit Baseline model first, never silent
    baseline_schema = None
    baseline_dataset = None
    if baseline_dataset_id:
        baseline_schema = db.query(models.SchemaRecord).filter(
            models.SchemaRecord.dataset_id == baseline_dataset_id
        ).order_by(desc(models.SchemaRecord.created_at)).first()
        baseline_dataset = db.query(models.Dataset).filter(models.Dataset.id == baseline_dataset_id).first()
    else:
        # First check active Baseline for this logical dataset (explicit, versioned)
        try:
            active = baseline_manager.get_active_baseline(db, dataset.name)
            if active and active.baseline_dataset_id != dataset_id:
                baseline_dataset = db.query(models.Dataset).filter(models.Dataset.id == active.baseline_dataset_id).first()
                baseline_schema = db.query(models.SchemaRecord).filter(
                    models.SchemaRecord.dataset_id == active.baseline_dataset_id
                ).order_by(desc(models.SchemaRecord.created_at)).first()
                # If active baseline points to missing schema, fallback to prefix search
                if not baseline_schema:
                    baseline_dataset = None
        except Exception:
            pass
        if not baseline_schema:
            # Check if there is an earlier dataset with the same name or prefix
            prefix = dataset.name.split("_v")[0]
            earlier_ds = db.query(models.Dataset).filter(
                models.Dataset.id != dataset_id,
                models.Dataset.name.like(f"{prefix}%")
            ).order_by(models.Dataset.created_at.asc()).first()
            if earlier_ds:
                baseline_schema = db.query(models.SchemaRecord).filter(
                    models.SchemaRecord.dataset_id == earlier_ds.id
                ).order_by(desc(models.SchemaRecord.created_at)).first()
                baseline_dataset = earlier_ds

    # Preload DataFrames for statistical drift (PSI/KS/JSD) — requires raw data
    df_current = None
    df_baseline = None
    def _load_df_for_dataset(ds) -> Optional[Any]:
        if not ds:
            return None
        try:
            exact_path = os.path.join(STORAGE_DIR, f"{ds.id}_{ds.filename}")
            stored_path = exact_path if os.path.exists(exact_path) else None
            if not stored_path:
                for fname in os.listdir(STORAGE_DIR):
                    if fname.startswith(f"{ds.id}_"):
                        if fname == f"{ds.id}_{ds.filename}":
                            stored_path = os.path.join(STORAGE_DIR, fname)
                            break
                if not stored_path:
                    for fname in os.listdir(STORAGE_DIR):
                        if fname.startswith(f"{ds.id}_"):
                            stored_path = os.path.join(STORAGE_DIR, fname)
                            break
            if not stored_path and ds.name in ("orders_v1","orders_v2_schema_drift","orders_bad_quality","customers_v1","products_v1"):
                for p in [os.path.abspath(os.path.join(STORAGE_DIR, "../../sample-data", f"{ds.name}.csv")),
                          os.path.abspath(os.path.join(os.path.dirname(__file__), "../../sample-data", f"{ds.name}.csv")),
                          os.path.join(os.path.dirname(__file__), f"../../sample-data/{ds.name}.csv")]:
                    if os.path.exists(p):
                        stored_path = p
                        break
            if stored_path and os.path.exists(stored_path):
                with open(stored_path, "rb") as fh:
                    content = fh.read()
                return parse_dataset_content(content, ds.filename or stored_path)
        except Exception:
            pass
        return None
    try:
        df_current = _load_df_for_dataset(dataset)
        if baseline_dataset:
            df_baseline = _load_df_for_dataset(baseline_dataset)
    except Exception:
        pass

    all_issues = []

    # 1. Deterministic Schema Drift Check - Watchtower-enhanced with row-count, null-rate, numeric, cardinality + statistical (PSI/KS/JSD)
    if baseline_schema:
        base_cols = [{
            "column_name": c.column_name,
            "data_type": c.data_type,
            "nullable": c.nullable,
            "null_count": c.null_count,
            "unique_count": c.unique_count,
            "null_rate": c.null_rate if c.null_rate is not None else 0.0,
            "unique_ratio": c.unique_ratio if c.unique_ratio is not None else 0.0,
            "mean": c.mean,
            "median": c.median,
            "min_value": c.min_value,
            "max_value": c.max_value,
            "p05": c.p05,
            "p95": c.p95,
            "outlier_count": c.outlier_count or 0,
            "outlier_rate": c.outlier_rate if c.outlier_rate is not None else 0.0,
            "top_values": c.top_values or [],
        } for c in baseline_schema.columns]
        baseline_row_count = baseline_dataset.row_count if baseline_dataset else None
        current_row_count = dataset.row_count
        drift_issues = detect_schema_drift(
            base_cols, curr_cols,
            baseline_row_count=baseline_row_count,
            current_row_count=current_row_count,
            baseline_df=df_baseline,
            current_df=df_current,
        )
        all_issues.extend(drift_issues)

    # 2. Deterministic Quality Checks - try comprehensive engine with stored file, fallback to metadata
    quality_ran = False
    df_quality = df_current  # reuse preloaded df if available
    if df_quality is not None:
        try:
            q_issues = run_quality_checks(df_quality, dataset_name=dataset.name)
            all_issues.extend(q_issues)
            quality_ran = True
        except Exception:
            quality_ran = False
            df_quality = None
    if not quality_ran:
        try:
            # Locate stored file for current dataset - exact match
            exact_path = os.path.join(STORAGE_DIR, f"{dataset.id}_{dataset.filename}")
            stored_path = exact_path if os.path.exists(exact_path) else None
            # Fallback: search by id prefix (for legacy)
            if not stored_path:
                for fname in os.listdir(STORAGE_DIR):
                    if fname.startswith(f"{dataset.id}_"):
                        # Ensure filename matches dataset's filename to avoid stale id collision
                        if fname == f"{dataset.id}_{dataset.filename}":
                            stored_path = os.path.join(STORAGE_DIR, fname)
                            break
                if not stored_path:
                    for fname in os.listdir(STORAGE_DIR):
                        if fname.startswith(f"{dataset.id}_"):
                            stored_path = os.path.join(STORAGE_DIR, fname)
                            break
            # Fallback for demo datasets that were seeded from sample-data
            if not stored_path and dataset.name in ("orders_v1","orders_v2_schema_drift","orders_bad_quality","customers_v1","products_v1"):
                candidate = os.path.abspath(os.path.join(STORAGE_DIR, "../../sample-data", f"{dataset.name}.csv"))
                alt = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../sample-data", f"{dataset.name}.csv"))
                for p in [candidate, alt, os.path.join(os.path.dirname(__file__), f"../../sample-data/{dataset.name}.csv")]:
                    if os.path.exists(p):
                        stored_path = p
                        break
            if stored_path and os.path.exists(stored_path):
                with open(stored_path, "rb") as fh:
                    content = fh.read()
                df_quality = parse_dataset_content(content, dataset.filename or stored_path)
                q_issues = run_quality_checks(df_quality, dataset_name=dataset.name)
                all_issues.extend(q_issues)
                quality_ran = True
        except Exception:
            quality_ran = False

    # 2b. Quality Contracts evaluation (SodaCL / GE suite inspired) — versioned, explainable
    try:
        contracts = qc_manager.get_contracts_for_dataset(db, dataset.name, only_enabled=True)
        if contracts and df_quality is not None:
            c_issues = qc_manager.evaluate_contracts(df_quality, dataset.name, contracts)
            all_issues.extend(c_issues)
        elif contracts and df_quality is None:
            # Metadata-only fallback: evaluate row_count contracts via dataset.row_count
            for c in contracts:
                if c.contract_type in ("row_count",):
                    params = c.params or {}
                    min_rc = params.get("min") or params.get("min_rows")
                    max_rc = params.get("max") or params.get("max_rows")
                    if min_rc is not None and dataset.row_count < min_rc:
                        all_issues.append({
                            "issue_type": "CONTRACT_BREACH_ROW_COUNT",
                            "severity": c.severity or "WARNING",
                            "column_name": None,
                            "description": f"Row count breach: {dataset.row_count} < min {min_rc} (contract v{c.version} for '{c.dataset_name}').",
                            "metadata": {"contract_id": c.id, "actual_row_count": dataset.row_count, "min": min_rc, "max": max_rc, "version": c.version},
                        })
                    elif max_rc is not None and dataset.row_count > max_rc:
                        all_issues.append({
                            "issue_type": "CONTRACT_BREACH_ROW_COUNT",
                            "severity": c.severity or "WARNING",
                            "column_name": None,
                            "description": f"Row count breach: {dataset.row_count} > max {max_rc} (contract v{c.version} for '{c.dataset_name}').",
                            "metadata": {"contract_id": c.id, "actual_row_count": dataset.row_count, "min": min_rc, "max": max_rc, "version": c.version},
                        })
    except Exception:
        pass  # contract evaluation must not break scan

    if not quality_ran:
        # Fallback metadata-only checks (covers cases where file not stored)
        for c in current_schema.columns:
            if c.column_name.lower().endswith("_id") and c.nullable and c.null_count > 0:
                all_issues.append({
                    "issue_type": "PRIMARY_KEY_NULL",
                    "severity": "CRITICAL",
                    "column_name": c.column_name,
                    "description": f"Identifier column '{c.column_name}' contains {c.null_count} NULL values.",
                    "metadata": {"null_count": c.null_count}
                })
            if c.null_count > 0 and dataset.row_count > 0:
                null_pct = round((c.null_count / dataset.row_count) * 100, 2)
                if null_pct > 15.0:
                    all_issues.append({
                        "issue_type": "HIGH_NULL_RATE",
                        "severity": "WARNING",
                        "column_name": c.column_name,
                        "description": f"Column '{c.column_name}' has a null rate of {null_pct}%.",
                        "metadata": {"null_count": c.null_count, "null_pct": null_pct}
                    })

    critical_count = sum(1 for iss in all_issues if iss["severity"] == "CRITICAL")
    warning_count = sum(1 for iss in all_issues if iss["severity"] == "WARNING")
    healthy_count = len(curr_cols) - (critical_count + warning_count)
    if healthy_count < 0:
        healthy_count = 0

    # Generate human-readable incident summary (Watchtower-adapted)
    try:
        baseline_rc = baseline_dataset.row_count if baseline_dataset else None
        incident_summary, incident_severity = generate_incident_summary(
            all_issues, baseline_row_count=baseline_rc, current_row_count=dataset.row_count
        )
    except Exception:
        incident_summary, incident_severity = ("Healthy profile change: no material drift detected.", "INFO")
        if critical_count > 0:
            incident_severity = "CRITICAL"
        elif warning_count > 0:
            incident_severity = "WARNING"

    # Phase 3: deterministic quality score with explainable dimensions
    try:
        score_data = compute_quality_score(all_issues, df_quality)
        quality_score_val = float(score_data["score"])
        quality_dimensions_val = score_data["dimensions"]
    except Exception:
        quality_score_val = 100.0 if not all_issues else max(0, 100 - sum(25 if i["severity"]=="CRITICAL" else 10 for i in all_issues))
        quality_dimensions_val = {}

    scan = models.Scan(
        dataset_id=dataset_id,
        baseline_dataset_id=baseline_dataset.id if baseline_dataset else None,
        status="COMPLETED",
        healthy_count=healthy_count,
        warning_count=warning_count,
        critical_count=critical_count,
        incident_summary=incident_summary,
        incident_severity=incident_severity,
        quality_score=quality_score_val,
        quality_dimensions=quality_dimensions_val,
        started_at=datetime.datetime.now(datetime.timezone.utc),
        completed_at=datetime.datetime.now(datetime.timezone.utc)
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    for iss in all_issues:
        issue_row = models.Issue(
            scan_id=scan.id,
            issue_type=iss["issue_type"],
            severity=iss["severity"],
            column_name=iss.get("column_name"),
            description=iss["description"],
            issue_metadata=iss.get("metadata", {})
        )
        db.add(issue_row)
    db.commit()
    db.refresh(scan)

    # Phase 7: Incident correlation — deterministic grouping of related issues
    try:
        persisted_issues = db.query(models.Issue).filter(models.Issue.scan_id == scan.id).all()
        incident_manager.correlate_incidents_for_scan(db, scan, persisted_issues)
        db.refresh(scan)
    except Exception:
        pass  # incident creation must not break scan

    return scan

@app.get("/api/scans", response_model=List[schemas.ScanResponse])
def list_scans(db: Session = Depends(get_db)):
    return db.query(models.Scan).order_by(desc(models.Scan.completed_at)).all()

@app.get("/api/scans/{scan_id}", response_model=schemas.ScanResponse)
def get_scan(scan_id: int, db: Session = Depends(get_db)):
    scan = db.query(models.Scan).filter(models.Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan

@app.get("/api/scans/{scan_id}/issues", response_model=List[schemas.IssueResponse])
def get_scan_issues(scan_id: int, db: Session = Depends(get_db)):
    return db.query(models.Issue).filter(models.Issue.scan_id == scan_id).all()

@app.get("/api/scans/{scan_id}/gate", response_model=schemas.GateResponse)
def get_scan_gate(
    scan_id: int,
    allowed_severity: str = "WARNING",
    max_row_count_drop_ratio: float = 0.15,
    max_null_drift_count: int = 0,
    max_numeric_drift_count: int = 0,
    max_cardinality_drift_count: int = 0,
    db: Session = Depends(get_db)
):
    scan = db.query(models.Scan).filter(models.Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    issues = db.query(models.Issue).filter(models.Issue.scan_id == scan_id).all()
    issues_data = [{"issue_type": i.issue_type, "severity": i.severity, "metadata": i.issue_metadata or {}} for i in issues]
    baseline_rc = None
    if scan.baseline_dataset_id:
        base_ds = db.query(models.Dataset).filter(models.Dataset.id == scan.baseline_dataset_id).first()
        if base_ds:
            baseline_rc = base_ds.row_count
    gate = assess_gate(
        issues_data,
        scan.incident_severity or "INFO",
        baseline_row_count=baseline_rc,
        current_row_count=scan.dataset.row_count if scan.dataset else None,
        allowed_severity=allowed_severity,
        max_row_count_drop_ratio=max_row_count_drop_ratio,
        max_null_drift_count=max_null_drift_count,
        max_numeric_drift_count=max_numeric_drift_count,
        max_cardinality_drift_count=max_cardinality_drift_count,
    )
    return gate

@app.get("/api/scans/{scan_id}/score", response_model=schemas.QualityScoreResponse)
def get_scan_score(scan_id: int, db: Session = Depends(get_db)):
    scan = db.query(models.Scan).filter(models.Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    # If score not computed (legacy scan), compute on fly from issues
    if scan.quality_score is not None and scan.quality_dimensions:
        dimensions = scan.quality_dimensions
        score = int(round(float(scan.quality_score)))
        # summary recompute for consistency
        from quality_score import compute_quality_score as _cqs
        issues = db.query(models.Issue).filter(models.Issue.scan_id == scan_id).all()
        issues_data = [{"issue_type": i.issue_type, "severity": i.severity, "metadata": i.issue_metadata or {}} for i in issues]
        # Try to load df for freshness dimension
        try:
            # reuse df if available
            from storage_backend import STORAGE_DIR
            import os
            exact_path = os.path.join(STORAGE_DIR, f"{scan.dataset.id}_{scan.dataset.filename}")
            stored_path = exact_path if os.path.exists(exact_path) else None
            if stored_path and os.path.exists(stored_path):
                from scanner import parse_dataset_content as _parse
                with open(stored_path, "rb") as fh:
                    content = fh.read()
                df = _parse(content, scan.dataset.filename or stored_path)
                recomputed = _cqs(issues_data, df)
            else:
                recomputed = _cqs(issues_data, None)
            summary = recomputed["summary"]
        except Exception:
            summary = f"Quality score {score}/100 — {'critical' if score <50 else 'degraded' if score <75 else 'good' if score <90 else 'excellent'}."
        return {"score": score, "dimensions": dimensions, "summary": summary}
    # Legacy fallback: compute from issues
    issues = db.query(models.Issue).filter(models.Issue.scan_id == scan_id).all()
    issues_data = [{"issue_type": i.issue_type, "severity": i.severity, "metadata": i.issue_metadata or {}} for i in issues]
    from quality_score import compute_quality_score as _cqs
    result = _cqs(issues_data, None)
    return result

@app.get("/api/datasets/{dataset_id}/scans", response_model=List[schemas.ScanResponse])
def list_dataset_scans(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return db.query(models.Scan).filter(models.Scan.dataset_id == dataset_id).order_by(desc(models.Scan.completed_at)).all()

@app.get("/api/datasets/{dataset_id}/history")
def get_dataset_history(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    scans = db.query(models.Scan).filter(models.Scan.dataset_id == dataset_id).order_by(models.Scan.completed_at.asc()).all()
    points = []
    for s in scans:
        # include business_impact from latest AI if available
        ai = db.query(models.AIAnalysis).filter(models.AIAnalysis.scan_id == s.id).order_by(desc(models.AIAnalysis.created_at)).first()
        points.append({
            "scan_id": s.id,
            "created_at": s.completed_at.isoformat() if s.completed_at else None,
            "incident_severity": s.incident_severity,
            "critical_count": s.critical_count,
            "warning_count": s.warning_count,
            "healthy_count": s.healthy_count,
            "incident_summary": s.incident_summary,
            "quality_score": float(s.quality_score) if s.quality_score is not None else None,
            "quality_dimensions": s.quality_dimensions or {},
            "business_impact": ai.business_impact if ai and ai.business_impact else None,
            "technical_impact": ai.technical_impact if ai and ai.technical_impact else None,
        })
    return {"dataset_id": dataset_id, "dataset_name": ds.name, "history": points}

@app.get("/api/dashboard/reliability-trend", response_model=List[schemas.ReliabilityTrendPoint])
def get_reliability_trend(days: int = 30, db: Session = Depends(get_db)):
    from datetime import timedelta
    now = datetime.datetime.now(datetime.timezone.utc)
    # Group scans by date
    scans = db.query(models.Scan).order_by(models.Scan.completed_at.asc()).all()
    # Bucket by day string
    buckets: dict[str, dict] = {}
    for s in scans:
        d = s.completed_at.date().isoformat() if s.completed_at else now.date().isoformat()
        if d not in buckets:
            buckets[d] = {"healthy": 0, "warning": 0, "critical": 0, "total": 0}
        if s.critical_count > 0:
            buckets[d]["critical"] += 1
        elif s.warning_count > 0:
            buckets[d]["warning"] += 1
        else:
            buckets[d]["healthy"] += 1
        buckets[d]["total"] += 1
    # Ensure last `days` days are represented
    trend = []
    for i in range(days):
        day = (now.date() - timedelta(days=days-1-i)).isoformat()
        b = buckets.get(day, {"healthy": 0, "warning": 0, "critical": 0, "total": 0})
        trend.append({"date": day, **b})
    return trend

@app.get("/api/dashboard/top-issues", response_model=List[schemas.TopIssueResponse])
def get_top_issues(limit: int = 5, db: Session = Depends(get_db)):
    issues = db.query(models.Issue).join(models.Scan).order_by(desc(models.Issue.id)).limit(limit*3).all()
    # Filter to most recent critical/warning per scan
    seen_scans = set()
    top = []
    for iss in issues:
        if iss.scan_id in seen_scans and len(top) >= limit:
            continue
        scan = db.query(models.Scan).filter(models.Scan.id == iss.scan_id).first()
        ds = scan.dataset if scan else None
        if iss.severity in ("CRITICAL", "WARNING"):
            top.append({
                "scan_id": iss.scan_id,
                "dataset_id": scan.dataset_id if scan else 0,
                "dataset_name": ds.name if ds else "unknown",
                "filename": ds.filename if ds else "",
                "severity": iss.severity,
                "issue_type": iss.issue_type,
                "column_name": iss.column_name,
                "description": iss.description,
                "created_at": scan.completed_at if scan and scan.completed_at else datetime.datetime.now(datetime.timezone.utc),
            })
            seen_scans.add(iss.scan_id)
        if len(top) >= limit:
            break
    return top[:limit]

@app.get("/api/dashboard/business-impact", response_model=List[schemas.BusinessImpactResponse])
def get_business_impact(db: Session = Depends(get_db)):
    # Define KPI map — demo lineage → business KPIs
    KPI_MAP = {
        "revenue": {"kpi": "Revenue reporting", "description": "Monthly revenue, LTV, Executive Dashboard"},
        "customer": {"kpi": "Customer segmentation", "description": "360 view, cohort retention, segmentation"},
        "marketing": {"kpi": "Marketing attribution", "description": "Attribution, campaign ROI"},
        "margin": {"kpi": "Margin analysis", "description": "Promotion effectiveness, profitability"},
        "inventory": {"kpi": "Inventory health", "description": "Stock levels, fulfillment"},
    }
    scans = db.query(models.Scan).order_by(desc(models.Scan.completed_at)).limit(50).all()
    # Aggregate per KPI
    kpi_status: dict[str, dict] = {v["kpi"]: {"status": "HEALTHY", "datasets": set(), "columns": set(), "description": v["description"]} for v in KPI_MAP.values()}
    # Map lineage keys to KPI
    lineage_to_kpi = {
        "orders.order_value": "Revenue reporting",
        "orders.order_amount": "Revenue reporting",
        "orders.customer_id": "Customer segmentation",
        "orders.discount": "Margin analysis",
        "orders.order_date": "Revenue reporting",
        "customers.signup_date": "Customer segmentation",
        "products.price": "Margin analysis",
        "marketing.campaign_id": "Marketing attribution",
        "inventory.stock": "Inventory health",
    }
    for scan in scans:
        if scan.critical_count == 0 and scan.warning_count == 0:
            continue
        issues = db.query(models.Issue).filter(models.Issue.scan_id == scan.id).all()
        for iss in issues:
            if not iss.column_name:
                continue
            key = f"{scan.dataset.name.lower()}.{iss.column_name.lower()}"
            kpi = lineage_to_kpi.get(key)
            if not kpi:
                # fallback heuristic
                if "revenue" in iss.column_name.lower() or "order_value" in iss.column_name.lower() or "order_amount" in iss.column_name.lower():
                    kpi = "Revenue reporting"
                elif "customer" in iss.column_name.lower():
                    kpi = "Customer segmentation"
                elif "discount" in iss.column_name.lower() or "margin" in iss.column_name.lower():
                    kpi = "Margin analysis"
                else:
                    continue
            entry = kpi_status[kpi]
            entry["datasets"].add(scan.dataset.name)
            entry["columns"].add(iss.column_name)
            if iss.severity == "CRITICAL":
                entry["status"] = "CRITICAL"
            elif entry["status"] != "CRITICAL" and iss.severity == "WARNING":
                entry["status"] = "AT RISK"
    result = []
    for kpi, v in kpi_status.items():
        result.append({
            "kpi": kpi,
            "status": v["status"],
            "affected_datasets": sorted(list(v["datasets"])),
            "affected_columns": sorted(list(v["columns"])),
            "description": v["description"],
        })
    # Order: CRITICAL first, AT RISK, then HEALTHY
    order = {"CRITICAL": 0, "AT RISK": 1, "HEALTHY": 2}
    result.sort(key=lambda x: order.get(x["status"], 3))
    return result

# ----------------- AI Analyst & Remediations -----------------
@app.post("/api/scans/{scan_id}/analyze", response_model=schemas.AIAnalysisResponse)
def analyze_scan_with_ai(scan_id: int, db: Session = Depends(get_db)):
    scan = db.query(models.Scan).filter(models.Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    issues = db.query(models.Issue).filter(models.Issue.scan_id == scan_id).all()
    issues_data = [{
        "issue_type": i.issue_type,
        "severity": i.severity,
        "column_name": i.column_name,
        "description": i.description,
        "metadata": i.issue_metadata or {}
    } for i in issues]

    # Collect downstream affected assets
    affected_assets = []
    for i in issues:
        if i.column_name:
            impact = get_downstream_impact(scan.dataset.name, i.column_name)
            for item in impact:
                if item["name"] not in affected_assets:
                    affected_assets.append(item["name"])

    # Historical context: last 3 scans for logical dataset (prefix) excluding current — enables P3 history-aware AI
    historical_context = []
    try:
        prefix = scan.dataset.name.split("_")[0] if scan.dataset and scan.dataset.name else ""
        # find dataset ids with same prefix
        related_ids = [scan.dataset_id]
        if prefix:
            related_ds = db.query(models.Dataset).filter(models.Dataset.name.like(f"{prefix}%")).all()
            related_ids = [d.id for d in related_ds]
        prior_scans = db.query(models.Scan).filter(models.Scan.dataset_id.in_(related_ids), models.Scan.id != scan.id).order_by(desc(models.Scan.completed_at)).limit(3).all()
        for ps in prior_scans:
            historical_context.append({
                "scan_id": ps.id,
                "incident_severity": ps.incident_severity,
                "incident_summary": ps.incident_summary,
                "critical_count": ps.critical_count,
                "warning_count": ps.warning_count,
                "completed_at": ps.completed_at.isoformat() if ps.completed_at else None,
            })
    except Exception:
        historical_context = []

    # Run AI Analyst (with deterministic fallback) — now history-aware
    analysis_dict = run_ai_analyst(scan.dataset.name, issues_data, affected_assets, historical_context)

    ai_record = models.AIAnalysis(
        scan_id=scan.id,
        severity=analysis_dict["severity"],
        summary=analysis_dict["summary"],
        root_cause=analysis_dict["root_cause"],
        impact=" -> ".join(analysis_dict["affected_assets"]) if analysis_dict["affected_assets"] else "None",
        technical_impact=analysis_dict.get("technical_impact") or " -> ".join(analysis_dict["affected_assets"]) if analysis_dict["affected_assets"] else "None",
        business_impact=analysis_dict.get("business_impact") or "No business impact calculated.",
        affected_assets=analysis_dict["affected_assets"],
        recommended_action=analysis_dict["recommended_action"],
        confidence=analysis_dict["confidence"],
        requires_human_approval=analysis_dict.get("requires_human_approval", True),
        created_at=datetime.datetime.now(datetime.timezone.utc)
    )
    db.add(ai_record)

    # Automatically create a pending remediation entry for human review
    remediation = models.Remediation(
        scan_id=scan.id,
        suggestion=analysis_dict["recommended_action"],
        status="PENDING"
    )
    db.add(remediation)
    db.commit()
    db.refresh(ai_record)

    return schemas.AIAnalysisResponse(
        id=ai_record.id,
        scan_id=scan.id,
        summary=ai_record.summary,
        severity=ai_record.severity,
        root_cause=ai_record.root_cause,
        impact=ai_record.impact,
        technical_impact=ai_record.technical_impact,
        business_impact=ai_record.business_impact,
        affected_assets=ai_record.affected_assets,
        recommended_action=ai_record.recommended_action,
        confidence=ai_record.confidence,
        requires_human_approval=ai_record.requires_human_approval,
        created_at=ai_record.created_at
    )

@app.post("/api/remediations/{remediation_id}/approve", response_model=schemas.RemediationResponse)
def approve_remediation(
    remediation_id: int,
    action: schemas.RemediationActionRequest,
    db: Session = Depends(get_db)
):
    rem = db.query(models.Remediation).filter(models.Remediation.id == remediation_id).first()
    if not rem:
        raise HTTPException(status_code=404, detail="Remediation not found")

    rem.status = "APPROVED"
    rem.decision_by = action.decision_by or "lead_engineer@dataguard.internal"
    rem.decision_at = datetime.datetime.now(datetime.timezone.utc)
    rem.notes = action.notes or "Approved by operator for production pipeline sync."
    db.commit()
    db.refresh(rem)
    return rem

@app.post("/api/remediations/{remediation_id}/reject", response_model=schemas.RemediationResponse)
def reject_remediation(
    remediation_id: int,
    action: schemas.RemediationActionRequest,
    db: Session = Depends(get_db)
):
    rem = db.query(models.Remediation).filter(models.Remediation.id == remediation_id).first()
    if not rem:
        raise HTTPException(status_code=404, detail="Remediation not found")

    rem.status = "REJECTED"
    rem.decision_by = action.decision_by or "lead_engineer@dataguard.internal"
    rem.decision_at = datetime.datetime.now(datetime.timezone.utc)
    rem.notes = action.notes or "Rejected by operator. Manual upstream verification needed."
    db.commit()
    db.refresh(rem)
    return rem

# ----------------- Lineage -----------------
@app.get("/api/lineage/config")
def get_lineage_config_endpoint():
    cfg = get_lineage_config()
    return {"config": cfg, "is_demo": True, "note": "Editable lineage_config.json — replace with OpenLineage/dbt in production."}

@app.put("/api/lineage/config")
def update_lineage_config(payload: dict, db: Session = Depends(get_db)):
    # Validate shape: keys are "dataset.column", values are list of assets
    try:
        # basic validation
        for k, v in payload.items():
            if "." not in k or not isinstance(v, list):
                raise ValueError(f"Invalid key {k}")
        CONFIG_PATH.write_text(_json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return {"status": "updated", "config": payload}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ----------------- Lineage Graph (OpenLineage/Marquez — Phase 8) -----------------
@app.post("/api/lineage/edges", response_model=schemas.LineageEdgeResponse)
def create_lineage_edge(payload: schemas.LineageEdgeCreate, db: Session = Depends(get_db)):
    try:
        edge = lineage_graph.create_edge(db, payload.model_dump())
        return edge
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/lineage/edges", response_model=List[schemas.LineageEdgeResponse])
def list_lineage_edges(
    source_dataset: Optional[str] = None,
    source_column: Optional[str] = None,
    target_dataset: Optional[str] = None,
    job_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    return lineage_graph.list_edges(db, source_dataset=source_dataset, source_column=source_column, target_dataset=target_dataset, job_name=job_name)

@app.delete("/api/lineage/edges/{edge_id}")
def delete_lineage_edge(edge_id: int, db: Session = Depends(get_db)):
    edge = db.query(models.LineageEdge).filter(models.LineageEdge.id == edge_id).first()
    if not edge:
        raise HTTPException(status_code=404, detail="Edge not found")
    db.delete(edge)
    db.commit()
    return {"status": "deleted", "edge_id": edge_id}

@app.get("/api/lineage/graph", response_model=schemas.LineageGraphResponse)
def get_lineage_graph_endpoint(
    dataset: str,
    column: Optional[str] = None,
    depth: int = 3,
    db: Session = Depends(get_db)
):
    if depth < 1 or depth > 5:
        raise HTTPException(status_code=400, detail="depth must be 1-5")
    return lineage_graph.get_lineage_graph(db, dataset, column, depth=depth)

@app.get("/api/lineage/{dataset}/downstream", response_model=schemas.LineageTraversalResponse)
def get_dataset_downstream(dataset: str, column: Optional[str] = None, depth: int = 3, db: Session = Depends(get_db)):
    if depth < 1 or depth > 5:
        raise HTTPException(status_code=400, detail="depth must be 1-5")
    return lineage_graph.traverse_graph(db, dataset, column, direction="downstream", max_depth=depth)

@app.get("/api/lineage/{dataset}/upstream", response_model=schemas.LineageTraversalResponse)
def get_dataset_upstream(dataset: str, column: Optional[str] = None, depth: int = 3, db: Session = Depends(get_db)):
    if depth < 1 or depth > 5:
        raise HTTPException(status_code=400, detail="depth must be 1-5")
    return lineage_graph.traverse_graph(db, dataset, column, direction="upstream", max_depth=depth)

@app.get("/api/lineage/{dataset_name}/{column_name}", response_model=schemas.ColumnImpactResponse)
def get_column_lineage(dataset_name: str, column_name: str, db: Session = Depends(get_db)):
    # Try DB-backed lineage first (OpenLineage/Marquez inspired)
    try:
        db_edges = lineage_graph.get_direct_downstream(db, dataset_name, column_name)
        if db_edges:
            downstream = []
            for e in db_edges:
                downstream.append(schemas.DownstreamAsset(
                    name=e["target_dataset"],
                    asset_type=e["target_type"],
                    relationship=e["relationship"]
                ))
            # Determine if demo: seeded edges are still demo until custom production lineage added
            try:
                # Check if any edge is custom (not seeded)
                # Seeded edges have description containing "Seeded" and created_by system
                has_custom = any(
                    not (e.get("description") and "Seeded" in e["description"])
                    for e in db_edges
                )
                # Also check DB for any custom edge for this dataset/column that is not seeded
                # For MVP, if we have any DB edge, check its source: if all are seeded, is_demo True
                is_demo_val = not has_custom
                demo_note = "DB-backed lineage (LineageEdge) — seeded from lineage_config.json, editable via POST /api/lineage/edges" if not is_demo_val else "Seeded demo lineage (LineageEdge) from lineage_config.json — replace with OpenLineage/dbt in production."
                return schemas.ColumnImpactResponse(
                    column_name=column_name,
                    dataset_name=dataset_name,
                    affected_assets=downstream,
                    is_demo=is_demo_val,
                    demo_note=demo_note
                )
            except Exception:
                return schemas.ColumnImpactResponse(
                    column_name=column_name,
                    dataset_name=dataset_name,
                    affected_assets=downstream,
                    is_demo=False,
                    demo_note="DB-backed lineage (LineageEdge) — seeded from lineage_config.json, editable via POST /api/lineage/edges"
                )
    except Exception:
        pass
    assets = get_downstream_impact(dataset_name, column_name)
    downstream = [schemas.DownstreamAsset(**a) for a in assets]
    demo = is_demo_lineage(dataset_name, column_name)
    return schemas.ColumnImpactResponse(
        column_name=column_name,
        dataset_name=dataset_name,
        affected_assets=downstream,
        is_demo=demo,
        demo_note="Static demo lineage from lineage_config.json — replace with OpenLineage/dbt in production."
    )


# ----------------- Quality Contracts (SodaCL / GE suite) -----------------
@app.post("/api/contracts", response_model=schemas.QualityContractResponse)
def create_quality_contract(payload: schemas.QualityContractCreate, db: Session = Depends(get_db)):
    # Validation mirrors Soda threshold semantics
    ct = payload.contract_type.lower()
    if ct not in {"completeness","uniqueness","range","regex","row_count","not_null","unique"}:
        raise HTTPException(status_code=400, detail=f"Invalid contract_type '{payload.contract_type}'. Valid: completeness, uniqueness, range, regex, row_count")
    if payload.threshold is not None and not (0.0 <= payload.threshold <= 1.0):
        raise HTTPException(status_code=400, detail="threshold must be between 0.0 and 1.0")
    if payload.severity not in {"CRITICAL","WARNING","INFO"}:
        raise HTTPException(status_code=400, detail="severity must be CRITICAL, WARNING or INFO")
    if ct in {"range","regex"} and not payload.params:
        raise HTTPException(status_code=400, detail=f"contract_type '{ct}' requires params (e.g., min/max for range, pattern for regex)")
    # Normalize dataset_name strip
    if not payload.dataset_name or not payload.dataset_name.strip():
        raise HTTPException(status_code=400, detail="dataset_name is required")
    try:
        contract = qc_manager.create_contract(db, payload.model_dump())
        return contract
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/contracts", response_model=List[schemas.QualityContractResponse])
def list_quality_contracts(dataset_name: Optional[str] = None, enabled: Optional[bool] = None, db: Session = Depends(get_db)):
    q = db.query(models.QualityContract)
    if dataset_name:
        # Use same matching logic as evaluation for discoverability: filter by exact or prefix
        # We fetch all and filter via python to keep matching consistent
        all_c = q.all()
        matched = [c for c in all_c if qc_manager._contract_matches(dataset_name, c.dataset_name) or c.dataset_name.lower() == dataset_name.lower()]
        # Also include exact dataset_name contracts
        if enabled is not None:
            matched = [c for c in matched if c.enabled == enabled]
        return sorted(matched, key=lambda x: x.id)
    if enabled is not None:
        q = q.filter(models.QualityContract.enabled == enabled)
    return q.order_by(models.QualityContract.id.asc()).all()

@app.get("/api/contracts/{contract_id}", response_model=schemas.QualityContractResponse)
def get_quality_contract(contract_id: int, db: Session = Depends(get_db)):
    c = db.query(models.QualityContract).filter(models.QualityContract.id == contract_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contract not found")
    return c

@app.put("/api/contracts/{contract_id}", response_model=schemas.QualityContractResponse)
def update_quality_contract(contract_id: int, payload: schemas.QualityContractUpdate, db: Session = Depends(get_db)):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "threshold" in data and data["threshold"] is not None and not (0.0 <= data["threshold"] <= 1.0):
        raise HTTPException(status_code=400, detail="threshold must be between 0.0 and 1.0")
    if "severity" in data and data["severity"] is not None and data["severity"] not in {"CRITICAL","WARNING","INFO"}:
        raise HTTPException(status_code=400, detail="severity must be CRITICAL, WARNING or INFO")
    if "contract_type" in data and data["contract_type"]:
        ct = data["contract_type"].lower()
        if ct not in {"completeness","uniqueness","range","regex","row_count","not_null","unique"}:
            raise HTTPException(status_code=400, detail=f"Invalid contract_type '{ct}'")
    c = qc_manager.update_contract(db, contract_id, data)
    if not c:
        raise HTTPException(status_code=404, detail="Contract not found")
    return c

@app.delete("/api/contracts/{contract_id}")
def delete_quality_contract(contract_id: int, db: Session = Depends(get_db)):
    ok = qc_manager.delete_contract(db, contract_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Contract not found")
    return {"status": "deleted", "contract_id": contract_id}

@app.get("/api/datasets/{dataset_id}/contracts", response_model=List[schemas.QualityContractResponse])
def get_dataset_contracts(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    contracts = qc_manager.get_contracts_for_dataset(db, ds.name, only_enabled=True)
    return contracts

@app.post("/api/datasets/{dataset_id}/contracts/evaluate")
def evaluate_dataset_contracts(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    contracts = qc_manager.get_contracts_for_dataset(db, ds.name, only_enabled=True)
    if not contracts:
        return {"dataset_id": dataset_id, "dataset_name": ds.name, "contracts_evaluated": 0, "breaches": []}
    # Load dfQuality as in scan
    try:
        exact_path = os.path.join(STORAGE_DIR, f"{ds.id}_{ds.filename}")
        stored_path = exact_path if os.path.exists(exact_path) else None
        if not stored_path:
            for fname in os.listdir(STORAGE_DIR):
                if fname.startswith(f"{ds.id}_"):
                    stored_path = os.path.join(STORAGE_DIR, fname)
                    break
        # sample-data fallback
        if not stored_path and ds.name in ("orders_v1","orders_v2_schema_drift","orders_bad_quality","customers_v1","products_v1"):
            candidate = os.path.abspath(os.path.join(STORAGE_DIR, "../../sample-data", f"{ds.name}.csv"))
            alt = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../sample-data", f"{ds.name}.csv"))
            for p in [candidate, alt]:
                if os.path.exists(p):
                    stored_path = p
                    break
        if not stored_path or not os.path.exists(stored_path):
            raise HTTPException(status_code=400, detail="Dataset file not available for contract evaluation")
        with open(stored_path, "rb") as fh:
            content = fh.read()
        df = parse_dataset_content(content, ds.filename or stored_path)
        breaches = qc_manager.evaluate_contracts(df, ds.name, contracts)
        return {"dataset_id": dataset_id, "dataset_name": ds.name, "contracts_evaluated": len(contracts), "breaches": breaches}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------- Baselines (explicit, versioned, never silent) -----------------
@app.post("/api/baselines", response_model=schemas.BaselineResponse)
def create_baseline(payload: schemas.BaselineCreate, db: Session = Depends(get_db)):
    try:
        # Resolve logical name
        if payload.dataset_name:
            logical = payload.dataset_name
        else:
            ds = db.query(models.Dataset).filter(models.Dataset.id == payload.baseline_dataset_id).first()
            if not ds:
                raise HTTPException(status_code=404, detail="Dataset not found")
            logical = ds.name
        baseline = baseline_manager.create_baseline(
            db,
            dataset_name=logical,
            baseline_dataset_id=payload.baseline_dataset_id,
            description=payload.description,
            created_by=payload.created_by or "system",
            set_active=payload.set_active,
        )
        return baseline
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/baselines", response_model=List[schemas.BaselineResponse])
def list_baselines(dataset_name: Optional[str] = None, active_only: bool = False, db: Session = Depends(get_db)):
    include_inactive = not active_only
    if dataset_name:
        baselines = baseline_manager.list_baselines(db, dataset_name, include_inactive=include_inactive)
    else:
        baselines = baseline_manager.list_baselines(db, None, include_inactive=include_inactive)
    return baselines

@app.get("/api/baselines/{baseline_id}", response_model=schemas.BaselineResponse)
def get_baseline(baseline_id: int, db: Session = Depends(get_db)):
    b = db.query(models.Baseline).filter(models.Baseline.id == baseline_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Baseline not found")
    return b

@app.put("/api/baselines/{baseline_id}/activate", response_model=schemas.BaselineResponse)
def activate_baseline_endpoint(baseline_id: int, db: Session = Depends(get_db)):
    b = baseline_manager.activate_baseline(db, baseline_id)
    if not b:
        raise HTTPException(status_code=404, detail="Baseline not found")
    return b

@app.put("/api/baselines/{baseline_id}", response_model=schemas.BaselineResponse)
def update_baseline(baseline_id: int, payload: schemas.BaselineUpdate, db: Session = Depends(get_db)):
    b = db.query(models.Baseline).filter(models.Baseline.id == baseline_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Baseline not found")
    if payload.description is not None:
        b.description = payload.description
    if payload.is_active is not None:
        if payload.is_active:
            # activate
            b = baseline_manager.activate_baseline(db, baseline_id)
        else:
            b = baseline_manager.deactivate_baseline(db, baseline_id)
        return b
    db.commit()
    db.refresh(b)
    return b

@app.delete("/api/baselines/{baseline_id}")
def delete_baseline_endpoint(baseline_id: int, db: Session = Depends(get_db)):
    ok = baseline_manager.delete_baseline(db, baseline_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Baseline not found")
    return {"status": "deleted", "baseline_id": baseline_id}

@app.get("/api/datasets/{dataset_id}/baselines", response_model=List[schemas.BaselineResponse])
def get_dataset_baselines(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    baselines = baseline_manager.list_baselines(db, ds.name, include_inactive=True)
    return baselines

@app.get("/api/baselines/{baseline_id}/compare/{dataset_id}")
def compare_baseline_to_dataset(baseline_id: int, dataset_id: int, db: Session = Depends(get_db)):
    b = db.query(models.Baseline).filter(models.Baseline.id == baseline_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Baseline not found")
    ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    # Use baseline's dataset and schema
    return baseline_manager.get_baseline_comparison(db, b, dataset_id)

# ----------------- Incidents (deterministic correlation) -----------------
@app.get("/api/incidents", response_model=List[schemas.IncidentResponse])
def list_incidents(
    dataset_id: Optional[int] = None,
    dataset_name: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    return incident_manager.list_incidents(db, dataset_id=dataset_id, dataset_name=dataset_name, severity=severity, status=status, limit=limit)

@app.get("/api/incidents/{incident_id}", response_model=schemas.IncidentResponse)
def get_incident(incident_id: int, db: Session = Depends(get_db)):
    inc = db.query(models.Incident).filter(models.Incident.id == incident_id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    return inc

@app.put("/api/incidents/{incident_id}", response_model=schemas.IncidentResponse)
def update_incident(incident_id: int, payload: schemas.IncidentStatusUpdate, db: Session = Depends(get_db)):
    inc = db.query(models.Incident).filter(models.Incident.id == incident_id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    if payload.status.upper() not in {"OPEN", "INVESTIGATING", "RESOLVED", "CLOSED"}:
        raise HTTPException(status_code=400, detail="Invalid status. Use OPEN, INVESTIGATING, RESOLVED, CLOSED")
    inc.status = payload.status.upper()
    if payload.status.upper() in ("RESOLVED", "CLOSED"):
        import datetime
        inc.resolved_at = datetime.datetime.now(datetime.timezone.utc)
        inc.resolved_by = payload.resolved_by or "system"
    else:
        inc.resolved_at = None
        inc.resolved_by = None
    import datetime
    inc.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(inc)
    return inc

@app.get("/api/scans/{scan_id}/incidents", response_model=List[schemas.IncidentResponse])
def get_scan_incidents(scan_id: int, db: Session = Depends(get_db)):
    scan = db.query(models.Scan).filter(models.Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return db.query(models.Incident).filter(models.Incident.scan_id == scan_id).order_by(desc(models.Incident.created_at)).all()

@app.get("/api/datasets/{dataset_id}/incidents", response_model=List[schemas.IncidentResponse])
def get_dataset_incidents(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return db.query(models.Incident).filter(models.Incident.dataset_id == dataset_id).order_by(desc(models.Incident.created_at)).all()

@app.get("/api/audit")
def get_audit_trail(
    limit: int = 20,
    dataset_id: Optional[int] = None,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    db: Session = Depends(get_db)
):
    # Governance: filterable audit for human verification
    q = db.query(models.Scan).order_by(desc(models.Scan.completed_at))
    if dataset_id:
        q = q.filter(models.Scan.dataset_id == dataset_id)
    if severity:
        q = q.filter(models.Scan.incident_severity == severity.upper())
    scans = q.limit(limit * 3).all()  # over-fetch for status filter
    trail = []
    for s in scans:
        if dataset_id and s.dataset_id != dataset_id:
            continue
        issues = db.query(models.Issue).filter(models.Issue.scan_id == s.id).all()
        ai = db.query(models.AIAnalysis).filter(models.AIAnalysis.scan_id == s.id).order_by(desc(models.AIAnalysis.created_at)).first()
        rems_q = db.query(models.Remediation).filter(models.Remediation.scan_id == s.id)
        if status:
            rems_q = rems_q.filter(models.Remediation.status == status.upper())
        rems = rems_q.all()
        for r in rems:
            if status and r.status != status.upper():
                continue
            if severity and s.incident_severity != severity.upper():
                continue
            trail.append({
                "scan_id": s.id,
                "dataset_id": s.dataset_id,
                "dataset_name": s.dataset.name if s.dataset else "",
                "filename": s.dataset.filename if s.dataset else "",
                "incident_summary": s.incident_summary,
                "incident_severity": s.incident_severity,
                "issue_count": len(issues),
                "ai_summary": ai.summary if ai else None,
                "business_impact": ai.business_impact if ai and ai.business_impact else None,
                "remediation_id": r.id,
                "suggestion": r.suggestion,
                "status": r.status,
                "decision_by": r.decision_by,
                "decision_at": r.decision_at.isoformat() if r.decision_at else None,
                "notes": r.notes,
                "scan_completed_at": s.completed_at.isoformat() if s.completed_at else None,
            })
    trail.sort(key=lambda x: x["decision_at"] or x["scan_completed_at"] or "", reverse=True)
    return trail[:limit]

# ----------------- 1-Click Interactive Demo Seed -----------------
@app.post("/api/demo/seed/{sample_name}")
def seed_demo_dataset(sample_name: str, db: Session = Depends(get_db)):
    allowed = {
        "orders_v1": "orders_v1.csv",
        "orders_v2_schema_drift": "orders_v2_schema_drift.csv",
        "orders_bad_quality": "orders_bad_quality.csv",
        "customers_v1": "customers_v1.csv",
        "products_v1": "products_v1.csv"
    }
    if sample_name not in allowed:
        raise HTTPException(status_code=400, detail=f"Unknown demo sample. Choose from: {list(allowed.keys())}")

    filename = allowed[sample_name]
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sample_path = os.path.abspath(os.path.join(current_dir, "../../sample-data", filename))
    if not os.path.exists(sample_path):
        sample_path = os.path.abspath(os.path.join(current_dir, "../sample-data", filename))
    if not os.path.exists(sample_path):
        raise HTTPException(status_code=404, detail=f"Sample file not found: {filename}")

    with open(sample_path, "rb") as f:
        content = f.read()

    df = parse_dataset_content(content, filename)
    row_count = len(df)
    column_count = len(df.columns)

    dataset = models.Dataset(
        name=sample_name,
        filename=filename,
        file_type="csv",
        row_count=row_count,
        column_count=column_count,
        created_at=datetime.datetime.now(datetime.timezone.utc)
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    # Persist demo file for quality checks
    try:
        save_file(dataset.id, filename, content)
    except Exception:
        pass

    # Profile schema
    column_profiles, fingerprint = profile_dataframe(df)
    schema_record = models.SchemaRecord(
        dataset_id=dataset.id,
        fingerprint=fingerprint,
        created_at=datetime.datetime.now(datetime.timezone.utc)
    )
    db.add(schema_record)
    db.commit()
    db.refresh(schema_record)

    for cp in column_profiles:
        sc = models.SchemaColumn(
            schema_id=schema_record.id,
            column_name=cp["column_name"],
            data_type=cp["data_type"],
            nullable=cp["nullable"],
            unique_count=cp["unique_count"],
            null_count=cp["null_count"],
            sample_values=cp["sample_values"],
            null_rate=cp.get("null_rate", 0.0),
            unique_ratio=cp.get("unique_ratio", 0.0),
            min_value=cp.get("min_value"),
            max_value=cp.get("max_value"),
            mean=cp.get("mean"),
            median=cp.get("median"),
            p05=cp.get("p05"),
            p95=cp.get("p95"),
            outlier_count=cp.get("outlier_count", 0),
            outlier_rate=cp.get("outlier_rate", 0.0),
            top_values=cp.get("top_values", []),
        )
        db.add(sc)
    db.commit()

    # Execute scan
    scan = scan_dataset(dataset.id, None, db)

    # Execute AI analysis
    analyze_scan_with_ai(scan.id, db)

    return {
        "status": "success",
        "dataset_id": dataset.id,
        "scan_id": scan.id,
        "filename": filename
    }
