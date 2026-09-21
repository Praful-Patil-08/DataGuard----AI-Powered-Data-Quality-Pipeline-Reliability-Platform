import os
os.environ["DATABASE_URL"] = "sqlite:///./test_incidents.db"
os.environ["OPENAI_API_KEY"] = ""
os.environ["AI_PROVIDER"] = "mock"

import pytest
from fastapi.testclient import TestClient

from database import engine, Base
import models
from main import app
import incidents as inc

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def _upload_and_scan(csv_bytes, name):
    res = client.post("/api/datasets/upload", files={"file": (name, csv_bytes, "text/csv")}, data={"dataset_name": name.replace(".csv","")})
    assert res.status_code == 200, res.text
    ds_id = res.json()["dataset_id"]
    res = client.post(f"/api/datasets/{ds_id}/scan")
    assert res.status_code == 200, res.text
    scan = res.json()
    return ds_id, scan["id"]

def test_incident_created_for_healthy_scan():
    csv = b"order_id,val\n1,10\n2,20\n3,30\n"
    ds_id, scan_id = _upload_and_scan(csv, "inc_healthy.csv")
    # Check incident via scan
    res = client.get(f"/api/scans/{scan_id}/incidents")
    assert res.status_code == 200
    incidents = res.json()
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc["scan_id"] == scan_id
    assert inc["dataset_id"] == ds_id
    assert inc["severity"] == "INFO" or inc["severity"] == "WARNING" or inc["severity"] == "PASSED" or inc["severity"] == "INFO"
    # For healthy, should be INFO or maybe WARNING? Our healthy scan has no critical, incident_severity INFO, so incident severity INFO
    assert inc["severity"] == "INFO"
    assert inc["status"] == "RESOLVED" or inc["status"] == "OPEN"
    assert inc["issue_count"] == 0
    assert inc["title"] is not None
    assert "correlation_evidence" in inc
    # Check via datasets endpoint
    res = client.get(f"/api/datasets/{ds_id}/incidents")
    assert len(res.json()) == 1

def test_incident_correlates_multiple_issues():
    # Use orders_bad_quality style with multiple issues + drift via baseline
    csv_v1 = b"order_id,customer_id,order_value\n1,101,100\n2,102,200\n"
    # Create baseline dataset
    res = client.post("/api/datasets/upload", files={"file": ("inc_multi_v1.csv", csv_v1, "text/csv")}, data={"dataset_name": "inc_multi"})
    v1_id = res.json()["dataset_id"]
    client.post("/api/baselines", json={"baseline_dataset_id": v1_id, "dataset_name": "inc_multi"})
    # Current with quality issues + schema/contract drift
    csv = b"order_id,customer_id,order_date,status,amount\n1,,invalid-date,COMPLETED,-10\n1,,2026-09-10,completed,-20\n2,102,2026-09-11,SHIPPED,30\n"
    ds_id, scan_id = _upload_and_scan(csv, "inc_multi_v2.csv")
    # Scan should use active baseline inc_multi
    res = client.get(f"/api/scans/{scan_id}/incidents")
    incidents = res.json()
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc["issue_count"] >= 3
    assert inc["severity"] == "CRITICAL"
    assert inc["status"] == "OPEN"
    # Affected columns should include multiple
    assert "customer_id" in inc["affected_columns"] or "order_id" in inc["affected_columns"]
    assert len(inc["affected_columns"]) >= 2
    # Issue types should include multiple families (quality + schema/drift)
    assert len(inc["issue_types"]) >= 2
    # Families in correlation evidence
    assert "families" in inc["correlation_evidence"]
    assert len(inc["correlation_evidence"]["families"]) >= 1
    # Overlapping columns or family counts
    assert "family_counts" in inc["correlation_evidence"]
    # Downstream assets via lineage
    assert "affected_assets" in inc
    # Root cause deterministic, not LLM
    assert inc["root_cause"] is not None
    assert len(inc["root_cause"]) > 10
    # Title deterministic
    assert inc["title"] is not None

def test_incident_schema_drift_grouping():
    # Create two datasets to trigger schema drift
    csv_v1 = b"order_id,order_value\n1,100.0\n2,200.0\n"
    csv_v2 = b"order_id,order_amount\n1,100.0\n2,200.0\n"
    res = client.post("/api/datasets/upload", files={"file": ("inc_schema_v1.csv", csv_v1, "text/csv")}, data={"dataset_name": "inc_schema"})
    v1_id = res.json()["dataset_id"]
    res = client.post("/api/datasets/upload", files={"file": ("inc_schema_v2.csv", csv_v2, "text/csv")}, data={"dataset_name": "inc_schema"})
    v2_id = res.json()["dataset_id"]
    # Create baseline for v1
    client.post("/api/baselines", json={"baseline_dataset_id": v1_id, "dataset_name": "inc_schema"})
    # Scan v2 with baseline v1
    res = client.post(f"/api/datasets/{v2_id}/scan?baseline_dataset_id={v1_id}")
    scan_id = res.json()["id"]
    res = client.get(f"/api/scans/{scan_id}/incidents")
    inc = res.json()[0]
    # Should have schema family
    assert "schema" in inc["correlation_evidence"]["families"]
    assert any("COLUMN_REMOVED" in t or "COLUMN_ADDED" in t or "COLUMN_RENAMED_CANDIDATE" in t for t in inc["issue_types"])
    # Root cause should mention schema
    assert "Schema" in inc["root_cause"] or "schema" in inc["root_cause"].lower()

def test_incident_contract_grouping():
    csv = b"order_id,amount\n1,10\n2,-5\n"
    ds_id, scan_id = _upload_and_scan(csv, "inc_contract.csv")
    # Create contract that will breach
    client.post("/api/contracts", json={"dataset_name": "inc_contract", "column_name": "amount", "contract_type": "range", "threshold": 1.0, "params": {"min": 0}, "severity": "CRITICAL"})
    # Need to re-scan to trigger contract (since contract created after first scan)
    res = client.post(f"/api/datasets/{ds_id}/scan")
    scan_id2 = res.json()["id"]
    res = client.get(f"/api/scans/{scan_id2}/incidents")
    inc = res.json()[0]
    assert "contract" in inc["correlation_evidence"]["families"]
    assert any("CONTRACT_BREACH" in t for t in inc["issue_types"])

def test_incident_status_update():
    csv = b"order_id,val\n1,10\n2,10\n"
    ds_id, scan_id = _upload_and_scan(csv, "inc_status.csv")
    # Make it critical via contract
    client.post("/api/contracts", json={"dataset_name": "inc_status", "column_name": "val", "contract_type": "range", "threshold": 1.0, "params": {"min": 100}, "severity": "CRITICAL"})
    res = client.post(f"/api/datasets/{ds_id}/scan")
    scan_id2 = res.json()["id"]
    res = client.get(f"/api/scans/{scan_id2}/incidents")
    inc_id = res.json()[0]["id"]
    assert res.json()[0]["status"] == "OPEN"
    # Update to RESOLVED
    res = client.put(f"/api/incidents/{inc_id}", json={"status": "RESOLVED", "resolved_by": "alice@test"})
    assert res.status_code == 200
    assert res.json()["status"] == "RESOLVED"
    assert res.json()["resolved_by"] == "alice@test"
    assert res.json()["resolved_at"] is not None
    # Update to CLOSED
    res = client.put(f"/api/incidents/{inc_id}", json={"status": "CLOSED"})
    assert res.json()["status"] == "CLOSED"

def test_incident_list_filtering():
    # Create two incidents with different severities
    csv_healthy = b"order_id,val\n1,10\n2,20\n"
    ds1, scan1 = _upload_and_scan(csv_healthy, "filter_healthy.csv")
    csv_bad = b"order_id,customer_id,amount\n1,, -10\n1,, -20\n"
    ds2, scan2 = _upload_and_scan(csv_bad, "filter_bad.csv")
    # Need to trigger contract for bad to make critical? Actually bad already has critical via PK
    res = client.get("/api/incidents?severity=CRITICAL")
    assert res.status_code == 200
    crits = res.json()
    assert len(crits) >= 1
    assert all(i["severity"] == "CRITICAL" for i in crits)
    res = client.get("/api/incidents?status=OPEN")
    assert all(i["status"] == "OPEN" for i in res.json())
    # Filter by dataset
    res = client.get(f"/api/incidents?dataset_id={ds1}")
    assert len(res.json()) == 1
    assert res.json()[0]["dataset_id"] == ds1

def test_incident_downstream_assets():
    # Use orders dataset which has lineage mapping for order_value -> revenue_model
    csv = b"order_id,customer_id,order_value\n1,101,100\n2,102,200\n"
    ds_id, scan_id = _upload_and_scan(csv, "orders_downstream.csv")
    # Create breach via completeness on order_value
    client.post("/api/contracts", json={"dataset_name": "orders", "column_name": "order_value", "contract_type": "completeness", "threshold": 1.0, "severity": "CRITICAL"})
    # Need to make order_value have null to breach (use orders prefix so lineage matches)
    csv_bad = b"order_id,customer_id,order_value\n1,101,\n2,102,200\n"
    res = client.post("/api/datasets/upload", files={"file": ("orders_downstream_bad.csv", csv_bad, "text/csv")}, data={"dataset_name": "orders"})
    bad_id = res.json()["dataset_id"]
    res = client.post(f"/api/datasets/{bad_id}/scan")
    scan_bad = res.json()["id"]
    res = client.get(f"/api/scans/{scan_bad}/incidents")
    inc = res.json()[0]
    # Should have downstream assets via lineage (orders.order_value -> revenue_model)
    assert len(inc["affected_assets"]) >= 1
    assert any("revenue" in a.lower() for a in inc["affected_assets"])

def test_incident_deterministic_not_llm():
    csv = b"order_id,val\n1,10\n2,20\n"
    ds_id, scan_id = _upload_and_scan(csv, "deterministic.csv")
    res = client.get(f"/api/scans/{scan_id}/incidents")
    inc1 = res.json()[0]
    # Re-fetch same incident should be same
    res = client.get(f"/api/incidents/{inc1['id']}")
    inc2 = res.json()
    assert inc1["title"] == inc2["title"]
    assert inc1["root_cause"] == inc2["root_cause"]
    assert inc1["severity"] == inc2["severity"]
    # Root cause should not contain LLM hallucination markers
    assert "OpenAI" not in inc1["root_cause"]
    assert "hallucination" not in inc1["root_cause"].lower()
