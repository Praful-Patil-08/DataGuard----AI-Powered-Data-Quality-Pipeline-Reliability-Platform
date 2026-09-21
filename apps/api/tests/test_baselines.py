import os
os.environ["DATABASE_URL"] = "sqlite:///./test_baselines.db"
os.environ["OPENAI_API_KEY"] = ""
os.environ["AI_PROVIDER"] = "mock"

import pytest
import pandas as pd
from fastapi.testclient import TestClient

from database import engine, Base
import models
from main import app
import baselines as bl

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

def test_baseline_crud_and_versioning():
    # Upload baseline dataset
    csv_v1 = b"order_id,order_value\n1,100.0\n2,200.0\n"
    v1_id = _upload_csv("orders_v1.csv", csv_v1)
    # Create baseline
    res = client.post("/api/baselines", json={"baseline_dataset_id": v1_id, "description": "Initial baseline", "created_by": "alice@test"})
    assert res.status_code == 200, res.text
    b1 = res.json()
    assert b1["version"] == 1
    assert b1["is_active"] is True
    assert b1["dataset_name"] == "orders"
    assert b1["fingerprint"] is not None
    assert b1["row_count"] == 2
    baseline_id_1 = b1["id"]

    # Create second baseline for same logical dataset (new version)
    csv_v2 = b"order_id,order_value\n1,100.0\n2,200.0\n3,300.0\n"
    v2_id = _upload_csv("orders_v2.csv", csv_v2)
    res = client.post("/api/baselines", json={"baseline_dataset_id": v2_id, "description": "Second baseline"})
    assert res.status_code == 200
    b2 = res.json()
    assert b2["version"] == 2
    assert b2["is_active"] is True
    # First should be deactivated
    res = client.get(f"/api/baselines/{baseline_id_1}")
    assert res.json()["is_active"] is False

    # List baselines
    res = client.get("/api/baselines?dataset_name=orders")
    assert res.status_code == 200
    assert len(res.json()) == 2

    # Activate first again
    res = client.put(f"/api/baselines/{baseline_id_1}/activate")
    assert res.status_code == 200
    assert res.json()["is_active"] is True
    # Second should be deactivated now
    res = client.get(f"/api/baselines/{b2['id']}")
    assert res.json()["is_active"] is False

    # Update description
    res = client.put(f"/api/baselines/{baseline_id_1}", json={"description": "Updated"})
    assert res.status_code == 200
    assert res.json()["description"] == "Updated"

    # Delete
    res = client.delete(f"/api/baselines/{b2['id']}")
    assert res.status_code == 200
    res = client.get(f"/api/baselines/{b2['id']}")
    assert res.status_code == 404

def test_baseline_active_used_in_scan():
    # Upload v1 and create baseline
    csv_v1 = b"order_id,order_value\n1,100.0\n2,200.0\n"
    v1_id = _upload_csv("orders_active_v1.csv", csv_v1)
    res = client.post("/api/baselines", json={"baseline_dataset_id": v1_id, "dataset_name": "orders_active"})
    assert res.status_code == 200
    baseline_id = res.json()["id"]
    # Upload v2 with drift (new column)
    csv_v2 = b"order_id,order_value,extra\n1,100.0,x\n2,200.0,y\n"
    v2_id = _upload_csv("orders_active_v2.csv", csv_v2)
    # Scan without explicit baseline_dataset_id should use active baseline
    res = client.post(f"/api/datasets/{v2_id}/scan")
    assert res.status_code == 200
    scan = res.json()
    # Should have drift because active baseline is v1 (extra column added)
    res = client.get(f"/api/scans/{scan['id']}/issues")
    issues = res.json()
    types = [i["issue_type"] for i in issues]
    assert "COLUMN_ADDED" in types
    # Verify scan's baseline_dataset_id is v1
    assert scan["baseline_dataset_id"] == v1_id

    # Now create new baseline for v2 and scan v3, should use new baseline
    csv_v3 = b"order_id,order_value,extra,another\n1,100.0,x,a\n"
    v3_id = _upload_csv("orders_active_v3.csv", csv_v3)
    # Before updating baseline, scan v3 should still compare to v1 (active is v1 currently? Actually we activated v1 earlier, but after creating v2 baseline, v2 was active. Wait we created v1 then v2, v2 was active, then we re-activated v1, so active is v1. Need to update to v2 now.)
    # Let's activate v2's baseline (need to find v2 baseline id - it was deleted? Actually we deleted v2 in previous test but not this one. In this test, we have baseline for v1 (id 1), and we will create for v2)
    res = client.post("/api/baselines", json={"baseline_dataset_id": v2_id, "dataset_name": "orders_active"})
    b_v2 = res.json()
    # Now active is v2
    res = client.post(f"/api/datasets/{v3_id}/scan")
    scan3 = res.json()
    res = client.get(f"/api/scans/{scan3['id']}/issues")
    issues3 = res.json()
    # Should compare v3 to v2 (v2 has extra, v3 has extra+another => only another added, not extra as added relative to v1)
    # Check that baseline is v2
    assert scan3["baseline_dataset_id"] == v2_id

def test_baseline_not_silent_after_scan():
    # Create baseline then scan multiple times, baseline should not change
    csv_v1 = b"order_id,val\n1,10\n2,20\n"
    v1_id = _upload_csv("stable_v1.csv", csv_v1)
    res = client.post("/api/baselines", json={"baseline_dataset_id": v1_id, "dataset_name": "stable"})
    b1_id = res.json()["id"]
    assert res.json()["is_active"] is True
    # Upload v2 and scan (should use baseline v1)
    csv_v2 = b"order_id,val\n1,10\n2,20\n3,30\n"
    v2_id = _upload_csv("stable_v2.csv", csv_v2)
    res = client.post(f"/api/datasets/{v2_id}/scan")
    assert res.json()["baseline_dataset_id"] == v1_id
    # Scan again v3
    csv_v3 = b"order_id,val\n1,10\n2,20\n3,30\n4,40\n"
    v3_id = _upload_csv("stable_v3.csv", csv_v3)
    res = client.post(f"/api/datasets/{v3_id}/scan")
    assert res.json()["baseline_dataset_id"] == v1_id  # still v1, not auto-updated to v2
    # Check active baseline still v1 (since we didn't change)
    res = client.get("/api/baselines?dataset_name=stable&active_only=true")
    active = res.json()[0]
    assert active["id"] == b1_id

def test_baseline_explicit_override():
    csv_v1 = b"order_id,val\n1,10\n"
    v1_id = _upload_csv("explicit_v1.csv", csv_v1)
    csv_v2 = b"order_id,val\n1,10\n2,20\n"
    v2_id = _upload_csv("explicit_v2.csv", csv_v2)
    csv_v3 = b"order_id,val\n1,10\n2,20\n3,30\n"
    v3_id = _upload_csv("explicit_v3.csv", csv_v3)
    # Create baseline for v1 as active
    client.post("/api/baselines", json={"baseline_dataset_id": v1_id, "dataset_name": "explicit"})
    # Scan v3 with explicit baseline_dataset_id=v2 should override active (v1)
    res = client.post(f"/api/datasets/{v3_id}/scan?baseline_dataset_id={v2_id}")
    assert res.status_code == 200
    assert res.json()["baseline_dataset_id"] == v2_id
    # Without explicit, should use active v1
    res = client.post(f"/api/datasets/{v3_id}/scan")
    assert res.json()["baseline_dataset_id"] == v1_id

def test_baseline_dataset_baselines_endpoint():
    csv_v1 = b"a,b\n1,2\n"
    v1_id = _upload_csv("endpoint_v1.csv", csv_v1)
    csv_v2 = b"a,b\n1,2\n3,4\n"
    v2_id = _upload_csv("endpoint_v2.csv", csv_v2)
    client.post("/api/baselines", json={"baseline_dataset_id": v1_id, "dataset_name": "endpoint_test"})
    client.post("/api/baselines", json={"baseline_dataset_id": v2_id, "dataset_name": "endpoint_test"})
    res = client.get(f"/api/datasets/{v1_id}/baselines")
    assert res.status_code == 200
    assert len(res.json()) == 2
    # Check compare endpoint
    baseline = res.json()[0]  # latest first? Ordered desc
    # Find active
    active = next(b for b in res.json() if b["is_active"])
    res = client.get(f"/api/baselines/{active['id']}/compare/{v1_id}")
    assert res.status_code == 200
    assert "baseline" in res.json()
    assert "candidate" in res.json()

def test_baseline_historical_view():
    # Ensure historical versions are kept and not overwritten
    csv_v1 = b"x,y\n1,1\n"
    v1_id = _upload_csv("hist_v1.csv", csv_v1)
    res = client.post("/api/baselines", json={"baseline_dataset_id": v1_id, "dataset_name": "hist_test", "description": "v1"})
    assert res.json()["version"] == 1
    csv_v2 = b"x,y\n1,1\n2,2\n"
    v2_id = _upload_csv("hist_v2.csv", csv_v2)
    res = client.post("/api/baselines", json={"baseline_dataset_id": v2_id, "dataset_name": "hist_test", "description": "v2"})
    assert res.json()["version"] == 2
    csv_v3 = b"x,y\n1,1\n2,2\n3,3\n"
    v3_id = _upload_csv("hist_v3.csv", csv_v3)
    res = client.post("/api/baselines", json={"baseline_dataset_id": v3_id, "dataset_name": "hist_test", "description": "v3"})
    assert res.json()["version"] == 3
    res = client.get("/api/baselines?dataset_name=hist_test")
    assert len(res.json()) == 3
    versions = sorted([b["version"] for b in res.json()])
    assert versions == [1,2,3]
    # Only one active
    active = [b for b in res.json() if b["is_active"]]
    assert len(active) == 1
    assert active[0]["version"] == 3

def test_baseline_with_quality_snapshot():
    csv_v1 = b"order_id,amount\n1,100\n2,200\n"
    v1_id = _upload_csv("qsnap_v1.csv", csv_v1)
    # Scan to generate quality_score
    res = client.post(f"/api/datasets/{v1_id}/scan")
    scan = res.json()
    assert "quality_score" in scan
    # Create baseline should snapshot quality_score
    res = client.post("/api/baselines", json={"baseline_dataset_id": v1_id, "dataset_name": "qsnap"})
    baseline = res.json()
    assert baseline["quality_score"] == scan["quality_score"]
    assert baseline["row_count"] == 2
    assert baseline["column_count"] == 2
