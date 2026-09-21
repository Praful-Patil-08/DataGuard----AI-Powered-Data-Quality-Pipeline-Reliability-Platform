import os
os.environ["DATABASE_URL"] = "sqlite:///./test_impact.db"
os.environ["OPENAI_API_KEY"] = ""
os.environ["AI_PROVIDER"] = "mock"

import pytest
from fastapi.testclient import TestClient

from database import engine, Base
import models
from main import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def test_column_impact_direct():
    # orders.order_value should have downstream revenue_model
    res = client.get("/api/impact/orders/order_value?severity=CRITICAL&depth=3")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["source"]["dataset"] == "orders"
    assert data["source"]["column"] == "order_value"
    assert data["total_assets"] >= 2
    # Check propagated severity and KPI
    assets = data["impacted_assets"]
    # First asset should be distance 1, CRITICAL
    first = [a for a in assets if a["distance"] == 1]
    assert len(first) >= 1
    assert any(a["propagated_severity"] == "CRITICAL" for a in first)
    # Check KPI
    assert any(a["kpi"] == "Revenue reporting" for a in assets)
    # Check evidence
    assert all("evidence" in a for a in assets)

def test_dataset_impact_without_column():
    res = client.get("/api/impact/orders?severity=WARNING&depth=2")
    assert res.status_code == 200
    data = res.json()
    assert data["source"]["column"] is None
    assert data["total_assets"] >= 1

def test_impact_depth_and_severity_propagation():
    # Create chain via lineage edges
    client.post("/api/lineage/edges", json={"source_dataset": "a", "source_column": "col", "target_dataset": "b", "target_type": "DATASET", "job_name": "j1"})
    client.post("/api/lineage/edges", json={"source_dataset": "b", "target_dataset": "c", "target_type": "DATASET", "job_name": "j2"})
    client.post("/api/lineage/edges", json={"source_dataset": "c", "target_dataset": "d", "target_type": "DASHBOARD", "job_name": "j3"})
    # Depth 1 should only reach b
    res = client.get("/api/impact/a/col?severity=CRITICAL&depth=1")
    assert res.json()["total_assets"] == 1
    assert res.json()["impacted_assets"][0]["target_dataset"] == "b"
    assert res.json()["impacted_assets"][0]["propagated_severity"] == "CRITICAL"
    # Depth 2 should reach b and c, with severity decay
    res = client.get("/api/impact/a/col?severity=CRITICAL&depth=2")
    assets = res.json()["impacted_assets"]
    assert len(assets) == 2
    # c at distance 2 should be WARNING (decay by 1)
    c_asset = next(a for a in assets if a["target_dataset"] == "c")
    assert c_asset["distance"] == 2
    assert c_asset["propagated_severity"] == "WARNING"
    # Depth 3 should reach d with INFO
    res = client.get("/api/impact/a/col?severity=CRITICAL&depth=3")
    d_asset = next(a for a in res.json()["impacted_assets"] if a["target_dataset"] == "d")
    assert d_asset["distance"] == 3
    assert d_asset["propagated_severity"] == "INFO"

def test_scan_impact():
    # Create dataset and scan with issues
    csv = b"order_id,customer_id,order_value\n1,101,100\n2,102,200\n"
    res = client.post("/api/datasets/upload", files={"file": ("scan_impact.csv", csv, "text/csv")}, data={"dataset_name": "orders"})
    ds_id = res.json()["dataset_id"]
    # Trigger contract breach on order_value to make critical
    client.post("/api/contracts", json={"dataset_name": "orders", "column_name": "order_value", "contract_type": "completeness", "threshold": 1.0, "severity": "CRITICAL"})
    csv_bad = b"order_id,customer_id,order_value\n1,101,\n2,102,200\n"
    res = client.post("/api/datasets/upload", files={"file": ("scan_impact_bad.csv", csv_bad, "text/csv")}, data={"dataset_name": "orders"})
    bad_id = res.json()["dataset_id"]
    res = client.post(f"/api/datasets/{bad_id}/scan")
    scan_id = res.json()["id"]
    res = client.get(f"/api/scans/{scan_id}/impact?depth=3")
    assert res.status_code == 200
    data = res.json()
    assert data["scan_id"] == scan_id
    assert data["dataset"] == "orders"
    assert data["total_assets"] >= 1
    assert "summary" in data
    # Check KPI impact
    assert len(data["kpi_impact"]) >= 1
    assert any(k["kpi"] == "Revenue reporting" for k in data["kpi_impact"])

def test_scan_impact_no_issues():
    csv = b"order_id,val\n1,10\n2,20\n"
    res = client.post("/api/datasets/upload", files={"file": ("no_issue.csv", csv, "text/csv")}, data={"dataset_name": "no_issue_test"})
    ds_id = res.json()["dataset_id"]
    res = client.post(f"/api/datasets/{ds_id}/scan")
    scan_id = res.json()["id"]
    res = client.get(f"/api/scans/{scan_id}/impact")
    assert res.status_code == 200
    assert res.json()["total_assets"] == 0 or "no downstream" in res.json()["summary"].lower()

def test_incident_impact():
    csv = b"order_id,customer_id,order_value\n1,101,100\n2,102,200\n"
    res = client.post("/api/datasets/upload", files={"file": ("inc_impact.csv", csv, "text/csv")}, data={"dataset_name": "orders"})
    ds_id = res.json()["dataset_id"]
    client.post("/api/contracts", json={"dataset_name": "orders", "column_name": "order_value", "contract_type": "completeness", "threshold": 1.0, "severity": "CRITICAL"})
    csv_bad = b"order_id,customer_id,order_value\n1,101,\n2,102,200\n"
    res = client.post("/api/datasets/upload", files={"file": ("inc_impact_bad.csv", csv_bad, "text/csv")}, data={"dataset_name": "orders"})
    bad_id = res.json()["dataset_id"]
    res = client.post(f"/api/datasets/{bad_id}/scan")
    scan_id = res.json()["id"]
    res = client.get(f"/api/scans/{scan_id}/incidents")
    inc_id = res.json()[0]["id"]
    res = client.get(f"/api/incidents/{inc_id}/impact?depth=2")
    assert res.status_code == 200
    data = res.json()
    assert data["scan_id"] == scan_id
    assert data["total_assets"] >= 1

def test_impact_no_downstream():
    res = client.get("/api/impact/unknown_dataset/unknown_col?depth=2")
    assert res.status_code == 200
    data = res.json()
    assert data["total_assets"] == 0
    assert "No downstream" in data["summary"]

def test_impact_deterministic():
    res1 = client.get("/api/impact/orders/order_value?severity=CRITICAL&depth=2")
    res2 = client.get("/api/impact/orders/order_value?severity=CRITICAL&depth=2")
    assert res1.json() == res2.json()

def test_impact_kpi_aggregation():
    # orders.customer_id should map to Customer segmentation
    res = client.get("/api/impact/orders/customer_id?severity=CRITICAL&depth=2")
    data = res.json()
    assert any(k["kpi"] == "Customer segmentation" for k in data["kpi_impact"])
