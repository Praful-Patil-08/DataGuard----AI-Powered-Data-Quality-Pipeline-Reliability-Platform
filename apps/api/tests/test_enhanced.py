import os
os.environ["DATABASE_URL"] = "sqlite:///./test_dataguard.db"
os.environ["OPENAI_API_KEY"] = ""
os.environ["AI_PROVIDER"] = "mock"

from fastapi.testclient import TestClient
from database import Base, engine
import models
from main import app
from scanner import profile_dataframe, parse_dataset_content
from drift import detect_schema_drift, generate_incident_summary, assess_gate
from ai import generate_fallback_analysis
import pathlib

client = TestClient(app)

def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

def test_scanner_extended_profiling():
    csv = b"order_id,order_value\n1,100.0\n2,200.0\n3,1000.0\n"
    df = parse_dataset_content(csv, "test.csv")
    profiles, fp = profile_dataframe(df)
    assert len(fp) == 64
    m = {p["column_name"]: p for p in profiles}
    assert "null_rate" in m["order_value"]
    assert "unique_ratio" in m["order_value"]
    assert m["order_value"]["mean"] == 433.333
    assert m["order_value"]["outlier_count"] == 0  # IQR with 3 values no outlier
    assert len(m["order_value"]["top_values"]) == 3
    assert m["order_value"]["top_values"][0]["value"] == "100.0"

def test_null_rate_drift_threshold():
    base = [{"column_name": "discount", "data_type": "FLOAT", "nullable": False, "null_count": 0, "unique_count": 5, "null_rate": 0.0, "unique_ratio": 0.625, "mean": 0.05, "outlier_rate": 0.0}]
    curr = [{"column_name": "discount", "data_type": "FLOAT", "nullable": True, "null_count": 1, "unique_count": 3, "null_rate": 0.167, "unique_ratio": 0.5, "mean": 0.05, "outlier_rate": 0.0}]
    issues = detect_schema_drift(base, curr, baseline_row_count=8, current_row_count=6)
    assert any(i["issue_type"] == "NULL_RATE_DRIFT" and i["severity"] == "WARNING" for i in issues)

def test_cardinality_collapse_severe():
    base = [{"column_name": "customer_id", "data_type": "INTEGER", "nullable": False, "null_count": 0, "unique_count": 8, "null_rate": 0.0, "unique_ratio": 1.0, "mean": 504.5, "outlier_rate": 0.0}]
    curr = [{"column_name": "customer_id", "data_type": "INTEGER", "nullable": False, "null_count": 0, "unique_count": 3, "null_rate": 0.0, "unique_ratio": 0.5, "mean": 504.5, "outlier_rate": 0.0}]
    issues = detect_schema_drift(base, curr, baseline_row_count=8, current_row_count=6)
    assert any(i["issue_type"] == "CARDINALITY_DRIFT" and i["severity"] == "CRITICAL" for i in issues)

def test_numeric_drift_critical():
    base = [{"column_name": "order_value", "data_type": "FLOAT", "nullable": False, "null_count": 0, "unique_count": 8, "null_rate": 0.0, "unique_ratio": 1.0, "mean": 842.594, "outlier_rate": 0.0}]
    curr = [{"column_name": "order_value", "data_type": "FLOAT", "nullable": False, "null_count": 0, "unique_count": 6, "null_rate": 0.0, "unique_ratio": 1.0, "mean": 4480.0, "outlier_rate": 0.167}]
    issues = detect_schema_drift(base, curr, baseline_row_count=8, current_row_count=6)
    assert any(i["issue_type"] == "NUMERIC_DRIFT" and i["severity"] == "CRITICAL" for i in issues)

def test_row_count_gate():
    base = [{"column_name": "a", "data_type": "INTEGER", "nullable": False, "null_count": 0, "unique_count": 2, "null_rate": 0.0, "unique_ratio": 1.0, "mean": 1.0, "outlier_rate": 0.0}]
    curr = [{"column_name": "a", "data_type": "INTEGER", "nullable": False, "null_count": 0, "unique_count": 2, "null_rate": 0.0, "unique_ratio": 1.0, "mean": 1.0, "outlier_rate": 0.0}]
    issues = detect_schema_drift(base, curr, baseline_row_count=8, current_row_count=6)
    summary, sev = generate_incident_summary(issues, 8, 6)
    assert sev == "CRITICAL"  # row drop 0.25 triggers critical
    gate = assess_gate(issues, sev, baseline_row_count=8, current_row_count=6, allowed_severity="WARNING")
    assert not gate["passed"]
    assert any("row-count drop" in r for r in gate["reasons"])

def test_incident_summary_business_friendly():
    issues = [
        {"issue_type": "COLUMN_REMOVED", "severity": "CRITICAL", "column_name": "order_value", "description": "", "metadata": {"previous_type": "FLOAT", "previous_nullable": False}},
        {"issue_type": "TYPE_CHANGED", "severity": "CRITICAL", "column_name": "discount", "description": "", "metadata": {"previous_type": "FLOAT", "current_type": "STRING"}},
    ]
    summary, sev = generate_incident_summary(issues, 8, 6)
    assert "Critical incident" in summary
    assert "columns removed: order_value" in summary
    assert sev == "CRITICAL"

def test_api_history_and_trend():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # seed v1
    with open("../../sample-data/orders_v1.csv","rb") as f:
        r = client.post("/api/datasets/upload", files={"file": ("orders_v1.csv", f, "text/csv")})
        assert r.status_code == 200
        v1 = r.json()["dataset_id"]
    r = client.post(f"/api/datasets/{v1}/scan")
    assert r.status_code == 200
    assert r.json()["incident_summary"] is not None
    r = client.get(f"/api/datasets/{v1}/scans")
    assert len(r.json()) == 1
    r = client.get(f"/api/datasets/{v1}/history")
    assert r.json()["history"][0]["incident_severity"] in ("INFO","HEALTHY","WARNING","CRITICAL") or "incident_severity" in r.json()["history"][0]
    r = client.get("/api/dashboard/reliability-trend?days=7")
    assert len(r.json()) == 7
    r = client.get("/api/dashboard/business-impact")
    assert any(x["kpi"] == "Revenue reporting" for x in r.json())
    r = client.get(f"/api/scans/1/gate")
    assert "passed" in r.json()

def test_ai_business_impact_split():
    issues = [
        {"issue_type": "COLUMN_REMOVED", "severity": "CRITICAL", "column_name": "order_value", "description": "order_value removed", "metadata": {}},
    ]
    res = generate_fallback_analysis("orders", issues, ["revenue_model"])
    assert "technical_impact" in res
    assert "business_impact" in res
    assert "Revenue" in res["business_impact"]
    assert "technical" in res["technical_impact"].lower() or "Schema" in res["technical_impact"]

def test_storage_quality_integration():
    # bad quality file should trigger quality issues via storage
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    import pathlib
    # ensure clean storage
    import shutil, os
    from main import STORAGE_DIR
    if os.path.exists(STORAGE_DIR):
        for f in os.listdir(STORAGE_DIR):
            try: os.remove(os.path.join(STORAGE_DIR, f))
            except: pass
    with open("../../sample-data/orders_v1.csv","rb") as f:
        r = client.post("/api/datasets/upload", files={"file": ("orders_v1.csv", f, "text/csv")})
        v1 = r.json()["dataset_id"]
    with open("../../sample-data/orders_bad_quality.csv","rb") as f:
        r = client.post("/api/datasets/upload", files={"file": ("orders_bad_quality.csv", f, "text/csv")})
        bad = r.json()["dataset_id"]
    r = client.post(f"/api/datasets/{bad}/scan?baseline_dataset_id={v1}")
    issues = client.get(f"/api/scans/{r.json()['id']}/issues").json()
    types = {i["issue_type"] for i in issues}
    assert "NEGATIVE_VALUE_ANOMALY" in types or "DUPLICATE_PRIMARY_KEY" in types
