import os
os.environ["DATABASE_URL"] = "sqlite:///./test_reliability.db"
os.environ["OPENAI_API_KEY"] = ""
os.environ["AI_PROVIDER"] = "mock"

import pytest
import time
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

def _upload_csv(name, csv_bytes):
    res = client.post("/api/datasets/upload", files={"file": (name, csv_bytes, "text/csv")}, data={"dataset_name": name.replace(".csv","")})
    assert res.status_code == 200, res.text
    return res.json()["dataset_id"]

def test_reliability_trends():
    # Create two datasets with scans on different days? For MVP, all scans today, so trend should have today bucket with scans
    csv_good = b"order_id,val\n1,10\n2,20\n3,30\n"
    csv_bad = b"order_id,customer_id,amount\n1,, -10\n1,, -20\n2,102,30\n"
    ds1 = _upload_csv("alpha_good.csv", csv_good)
    client.post(f"/api/datasets/{ds1}/scan")
    ds2 = _upload_csv("beta_bad.csv", csv_bad)
    client.post(f"/api/datasets/{ds2}/scan")
    res = client.get("/api/reliability/trends?days=7")
    assert res.status_code == 200
    trends = res.json()
    assert len(trends) == 7
    # Today should have 2 scans
    today = trends[-1]
    assert today["scans"] == 2
    assert today["avg_quality_score"] is not None
    # Filter by dataset (alpha prefix should only match ds1)
    res = client.get(f"/api/reliability/trends?dataset_id={ds1}&days=7")
    assert res.status_code == 200
    assert res.json()[-1]["scans"] == 1

def test_reliability_datasets_ranking():
    # Good dataset
    csv_good = b"order_id,val\n1,10\n2,20\n"
    ds_good = _upload_csv("rank_good.csv", csv_good)
    client.post(f"/api/datasets/{ds_good}/scan")
    # Bad dataset: multiple scans with low quality
    csv_bad = b"order_id,customer_id,amount\n1,, -10\n1,, -20\n"
    ds_bad = _upload_csv("rank_bad.csv", csv_bad)
    client.post(f"/api/datasets/{ds_bad}/scan")
    client.post(f"/api/datasets/{ds_bad}/scan")  # second scan
    res = client.get("/api/reliability/datasets?limit=5")
    assert res.status_code == 200
    datasets = res.json()
    assert len(datasets) >= 2
    # Most problematic should be bad (lowest avg_quality_score)
    assert datasets[0]["dataset_id"] == ds_bad
    assert datasets[0]["avg_quality_score"] < datasets[1]["avg_quality_score"]
    assert "total_critical" in datasets[0]
    assert "total_incidents" in datasets[0]

def test_reliability_columns_ranking():
    csv = b"order_id,customer_id,order_value\n1,,100\n1,,200\n2,102,300\n"
    ds_id = _upload_csv("col_rank.csv", csv)
    client.post(f"/api/datasets/{ds_id}/scan")
    # Also create contract breach on order_value to make it more problematic
    client.post("/api/contracts", json={"dataset_name": "col_rank", "column_name": "order_value", "contract_type": "completeness", "threshold": 1.0, "severity": "CRITICAL"})
    csv_bad = b"order_id,customer_id,order_value\n1,,100\n1,,200\n2,102,\n"
    ds2 = _upload_csv("col_rank2.csv", csv_bad)
    client.post(f"/api/datasets/{ds2}/scan")
    res = client.get("/api/reliability/columns?limit=5")
    assert res.status_code == 200
    cols = res.json()
    assert len(cols) >= 1
    # Most problematic should be customer_id or order_value
    top = cols[0]
    assert "column" in top
    assert "issue_count" in top
    assert top["issue_count"] >= 1
    assert "critical_count" in top

def test_incident_frequency():
    csv = b"order_id,val\n1,10\n2,20\n"
    ds_id = _upload_csv("inc_freq.csv", csv)
    client.post(f"/api/datasets/{ds_id}/scan")
    # Should have at least 1 incident for that scan
    res = client.get("/api/reliability/incidents?days=7")
    assert res.status_code == 200
    freq = res.json()
    assert len(freq) == 7
    assert freq[-1]["incidents"] >= 1
    # Filter by dataset
    res = client.get(f"/api/reliability/incidents?dataset_id={ds_id}&days=7")
    assert res.json()[-1]["incidents"] == 1

def test_quality_degradation():
    # Create scans with decreasing quality: first healthy, then degraded
    csv_good = b"order_id,val\n1,10\n2,20\n3,30\n4,40\n5,50\n"
    for i in range(5):
        ds_id = _upload_csv(f"degrade_good_{i}.csv", csv_good)
        client.post(f"/api/datasets/{ds_id}/scan")
    # Now bad scans
    csv_bad = b"order_id,customer_id,amount\n1,, -10\n1,, -20\n2,102,30\n3,103,40\n4,104,50\n"
    for i in range(5):
        ds_id = _upload_csv(f"degrade_bad_{i}.csv", csv_bad)
        client.post(f"/api/datasets/{ds_id}/scan")
    res = client.get("/api/reliability/degradation?window=5")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    # Since recent are bad (low score) and historical are good (high), should be degraded
    assert data["status"] in ("degraded", "stable", "insufficient_data")
    if data["status"] != "insufficient_data":
        assert "recent_avg" in data
        assert "historical_avg" in data
        assert "delta" in data
        assert "evidence" in data
        # Recent should be lower than historical
        assert data["recent_avg"] < data["historical_avg"]

def test_reliability_overview():
    csv = b"order_id,val\n1,10\n2,20\n"
    ds_id = _upload_csv("overview.csv", csv)
    client.post(f"/api/datasets/{ds_id}/scan")
    res = client.get("/api/reliability/overview")
    assert res.status_code == 200
    data = res.json()
    assert "total_scans" in data
    assert "total_incidents" in data
    assert "total_datasets" in data
    assert "avg_quality_score" in data
    assert "degradation" in data
    assert "most_problematic_datasets" in data
    assert "most_problematic_columns" in data
    assert "recent_incidents_7d" in data

def test_reliability_insufficient_data():
    # Fresh DB with no scans
    res = client.get("/api/reliability/degradation?window=5")
    assert res.status_code == 200
    assert res.json()["status"] == "insufficient_data"
