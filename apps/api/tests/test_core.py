import os
import pytest
import pandas as pd
from fastapi.testclient import TestClient

# Ensure sqlite for testing
os.environ["DATABASE_URL"] = "sqlite:///./test_dataguard.db"
os.environ["OPENAI_API_KEY"] = "" # Force deterministic fallback for hermetic tests

from database import engine, Base, SessionLocal
import models
from main import app
from scanner import profile_dataframe, parse_dataset_content, infer_column_datatype
from drift import detect_schema_drift
from quality import run_quality_checks
from lineage import get_downstream_impact
from ai import run_ai_analyst

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "connected" in data["database"]

def test_scanner_profiling():
    csv_data = b"id,val,active,date\n1,10.5,true,2026-01-01\n2,20.0,false,2026-01-02\n"
    df = parse_dataset_content(csv_data, "test.csv")
    assert len(df) == 2
    assert list(df.columns) == ["id", "val", "active", "date"]

    profiles, fingerprint = profile_dataframe(df)
    assert len(fingerprint) == 64
    prof_map = {p["column_name"]: p for p in profiles}
    assert prof_map["id"]["data_type"] == "INTEGER"
    assert prof_map["val"]["data_type"] == "FLOAT"
    assert prof_map["date"]["data_type"] == "DATE"

def test_schema_drift_detection():
    baseline = [
        {"column_name": "order_id", "data_type": "INTEGER", "nullable": False, "null_count": 0},
        {"column_name": "order_value", "data_type": "FLOAT", "nullable": False, "null_count": 0},
        {"column_name": "discount", "data_type": "FLOAT", "nullable": False, "null_count": 0},
    ]
    current = [
        {"column_name": "order_id", "data_type": "INTEGER", "nullable": False, "null_count": 0},
        {"column_name": "order_amount", "data_type": "FLOAT", "nullable": False, "null_count": 0},
        {"column_name": "discount", "data_type": "STRING", "nullable": True, "null_count": 1},
    ]

    issues = detect_schema_drift(baseline, current)
    types = [i["issue_type"] for i in issues]
    assert "COLUMN_REMOVED" in types # order_value removed
    assert "COLUMN_ADDED" in types   # order_amount added
    assert "TYPE_CHANGED" in types   # discount float -> string
    assert "NULLABILITY_CHANGED" in types

    # Verify severity
    removed_issue = next(i for i in issues if i["issue_type"] == "COLUMN_REMOVED")
    assert removed_issue["severity"] == "CRITICAL"
    type_issue = next(i for i in issues if i["issue_type"] == "TYPE_CHANGED")
    assert type_issue["severity"] == "CRITICAL"

def test_quality_checks():
    df = pd.DataFrame({
        "order_id": [101, 102, 102, None], # Duplicate & null
        "price": [50.0, -10.0, 100.0, 25000.0], # Negative & outlier
        "order_date": ["2026-01-01", "2026-01-02", "bad-date-str", "2026-01-04"],
        "status": ["COMPLETED", "completed", "SHIPPED", "SHIPPED"] # Casing inconsistency
    })

    issues = run_quality_checks(df)
    types = [i["issue_type"] for i in issues]
    assert "PRIMARY_KEY_NULL" in types
    assert "DUPLICATE_PRIMARY_KEY" in types
    assert "NEGATIVE_VALUE_ANOMALY" in types
    assert "MALFORMED_DATE" in types
    assert "CATEGORICAL_INCONSISTENCY" in types

def test_downstream_impact_lineage():
    impact = get_downstream_impact("orders", "order_value")
    asset_names = [a["name"] for a in impact]
    assert "revenue_model" in asset_names
    assert "monthly_revenue" in asset_names
    assert "Executive Revenue Dashboard" in asset_names

def test_ai_analyst_deterministic_fallback():
    issues = [
        {
            "issue_type": "COLUMN_REMOVED",
            "severity": "CRITICAL",
            "column_name": "order_value",
            "description": "order_value removed",
            "metadata": {}
        },
        {
            "issue_type": "COLUMN_ADDED",
            "severity": "WARNING",
            "column_name": "order_amount",
            "description": "order_amount added",
            "metadata": {}
        }
    ]
    res = run_ai_analyst("orders_v2", issues, ["revenue_model", "Executive Dashboard"])
    assert res["severity"] == "CRITICAL"
    assert "order_amount" in res["root_cause"] or "order_value" in res["root_cause"]
    assert res["requires_human_approval"] is True
    assert "revenue_model" in res["affected_assets"]

def test_full_api_workflow():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sample_dir = os.path.abspath(os.path.join(current_dir, "../../../sample-data"))
    orders_v1_path = os.path.join(sample_dir, "orders_v1.csv")
    orders_v2_path = os.path.join(sample_dir, "orders_v2_schema_drift.csv")

    # 1. Upload Baseline Dataset (orders_v1.csv)
    with open(orders_v1_path, "rb") as f:
        res = client.post("/api/datasets/upload", files={"file": ("orders_v1.csv", f, "text/csv")})
    assert res.status_code == 200
    base_id = res.json()["dataset_id"]

    # 2. Upload Drifted Dataset (orders_v2_schema_drift.csv)
    with open(orders_v2_path, "rb") as f:
        res = client.post("/api/datasets/upload", files={"file": ("orders_v2_schema_drift.csv", f, "text/csv")})
    assert res.status_code == 200
    v2_id = res.json()["dataset_id"]

    # 3. Trigger Scan on v2 with baseline
    res = client.post(f"/api/datasets/{v2_id}/scan?baseline_dataset_id={base_id}")
    assert res.status_code == 200
    scan = res.json()
    assert scan["critical_count"] > 0
    scan_id = scan["id"]

    # 4. Fetch Scan Issues
    res = client.get(f"/api/scans/{scan_id}/issues")
    assert res.status_code == 200
    issues = res.json()
    assert len(issues) >= 2

    # 5. Run AI Analysis
    res = client.post(f"/api/scans/{scan_id}/analyze")
    assert res.status_code == 200
    ai = res.json()
    assert ai["severity"] == "CRITICAL"
    assert ai["requires_human_approval"] is True

    # 6. Fetch Scan to verify pending remediation
    res = client.get(f"/api/scans/{scan_id}")
    scan_detail = res.json()
    assert len(scan_detail["remediations"]) == 1
    rem_id = scan_detail["remediations"][0]["id"]
    assert scan_detail["remediations"][0]["status"] == "PENDING"

    # 7. Approve Remediation
    res = client.post(f"/api/remediations/{rem_id}/approve", json={"decision_by": "praful@dataguard.ai", "notes": "Approved schema mapping."})
    assert res.status_code == 200
    assert res.json()["status"] == "APPROVED"
    assert res.json()["decision_by"] == "praful@dataguard.ai"
