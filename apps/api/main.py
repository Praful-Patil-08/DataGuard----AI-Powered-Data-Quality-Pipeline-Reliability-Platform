import os
import datetime
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import engine, Base, get_db
import models
import schemas
from scanner import parse_dataset_content, profile_dataframe
from drift import detect_schema_drift
from quality import run_quality_checks
from lineage import get_downstream_impact
from ai import run_ai_analyst

# Create all database tables on application startup
models.Base.metadata.create_all(bind=engine)

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
    if len(content) > 50 * 1024 * 1024: # 50MB limit
        raise HTTPException(status_code=400, detail="File exceeds maximum size limit (50MB).")

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

    # Save columns
    for cp in column_profiles:
        sc = models.SchemaColumn(
            schema_id=schema_record.id,
            column_name=cp["column_name"],
            data_type=cp["data_type"],
            nullable=cp["nullable"],
            unique_count=cp["unique_count"],
            null_count=cp["null_count"],
            sample_values=cp["sample_values"]
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
        "unique_count": c.unique_count
    } for c in current_schema.columns]

    # Look for baseline schema
    baseline_schema = None
    if baseline_dataset_id:
        baseline_schema = db.query(models.SchemaRecord).filter(
            models.SchemaRecord.dataset_id == baseline_dataset_id
        ).order_by(desc(models.SchemaRecord.created_at)).first()
    else:
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

    all_issues = []

    # 1. Deterministic Schema Drift Check
    if baseline_schema:
        base_cols = [{
            "column_name": c.column_name,
            "data_type": c.data_type,
            "nullable": c.nullable,
            "null_count": c.null_count,
            "unique_count": c.unique_count
        } for c in baseline_schema.columns]
        drift_issues = detect_schema_drift(base_cols, curr_cols)
        all_issues.extend(drift_issues)

    # 2. Deterministic Quality Checks
    # We inspect column metadata for immediate deterministic quality flags
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

    scan = models.Scan(
        dataset_id=dataset_id,
        status="COMPLETED",
        healthy_count=healthy_count,
        warning_count=warning_count,
        critical_count=critical_count,
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

    # Run AI Analyst (with deterministic fallback)
    analysis_dict = run_ai_analyst(scan.dataset.name, issues_data, affected_assets)

    ai_record = models.AIAnalysis(
        scan_id=scan.id,
        severity=analysis_dict["severity"],
        summary=analysis_dict["summary"],
        root_cause=analysis_dict["root_cause"],
        impact=" -> ".join(analysis_dict["affected_assets"]) if analysis_dict["affected_assets"] else "None",
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
@app.get("/api/lineage/{dataset_name}/{column_name}", response_model=schemas.ColumnImpactResponse)
def get_column_lineage(dataset_name: str, column_name: str):
    assets = get_downstream_impact(dataset_name, column_name)
    downstream = [schemas.DownstreamAsset(**a) for a in assets]
    return schemas.ColumnImpactResponse(
        column_name=column_name,
        dataset_name=dataset_name,
        affected_assets=downstream
    )

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
            sample_values=cp["sample_values"]
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
