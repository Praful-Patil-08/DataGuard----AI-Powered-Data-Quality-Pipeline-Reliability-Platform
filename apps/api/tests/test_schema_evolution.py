import os
os.environ["DATABASE_URL"] = "sqlite:///./test_schema_evol.db"
os.environ["OPENAI_API_KEY"] = ""
os.environ["AI_PROVIDER"] = "mock"

import pytest
import pandas as pd
from fastapi.testclient import TestClient

from database import engine, Base
import models
from main import app
from drift import detect_schema_drift

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def test_rename_candidate_likely():
    # order_value -> order_amount similar names, same type FLOAT, similar stats => likely
    baseline = [
        {"column_name": "order_id", "data_type": "INTEGER", "nullable": False, "null_count": 0, "unique_count": 8, "null_rate": 0.0, "unique_ratio": 1.0, "mean": 1005.5, "outlier_rate": 0.0},
        {"column_name": "order_value", "data_type": "FLOAT", "nullable": False, "null_count": 0, "unique_count": 8, "null_rate": 0.0, "unique_ratio": 1.0, "mean": 842.5, "outlier_rate": 0.0},
        {"column_name": "discount", "data_type": "FLOAT", "nullable": False, "null_count": 0, "unique_count": 5, "null_rate": 0.0, "unique_ratio": 0.6, "mean": 0.05, "outlier_rate": 0.0},
    ]
    current = [
        {"column_name": "order_id", "data_type": "INTEGER", "nullable": False, "null_count": 0, "unique_count": 6, "null_rate": 0.0, "unique_ratio": 1.0, "mean": 1011.5, "outlier_rate": 0.0},
        {"column_name": "order_amount", "data_type": "FLOAT", "nullable": False, "null_count": 0, "unique_count": 6, "null_rate": 0.0, "unique_ratio": 1.0, "mean": 845.0, "outlier_rate": 0.0},
        {"column_name": "discount", "data_type": "FLOAT", "nullable": False, "null_count": 0, "unique_count": 5, "null_rate": 0.0, "unique_ratio": 0.6, "mean": 0.05, "outlier_rate": 0.0},
    ]
    issues = detect_schema_drift(baseline, current, baseline_row_count=8, current_row_count=6)
    types = [i["issue_type"] for i in issues]
    # Should have removed, added, and rename candidate
    assert "COLUMN_REMOVED" in types
    assert "COLUMN_ADDED" in types
    assert "COLUMN_RENAMED_CANDIDATE" in types
    cand = next(i for i in issues if i["issue_type"] == "COLUMN_RENAMED_CANDIDATE")
    assert cand["metadata"]["from_column"] == "order_value"
    assert cand["metadata"]["to_column"] == "order_amount"
    assert cand["metadata"]["confidence"] >= 0.60
    assert "evidence" in cand["metadata"]
    assert cand["metadata"]["evidence"]["name_similarity"] >= 0.4
    assert cand["severity"] == "INFO"  # never critical
    # Ensure we did not suppress original removed/added
    assert any(i["column_name"] == "order_value" for i in issues if i["issue_type"] == "COLUMN_REMOVED")
    assert any(i["column_name"] == "order_amount" for i in issues if i["issue_type"] == "COLUMN_ADDED")

def test_rename_candidate_not_false_positive():
    # Completely different names and types should not produce candidate
    baseline = [
        {"column_name": "customer_id", "data_type": "INTEGER", "nullable": False, "null_count": 0, "unique_count": 5, "null_rate": 0.0, "unique_ratio": 1.0, "mean": 501, "outlier_rate": 0.0},
    ]
    current = [
        {"column_name": "product_price", "data_type": "STRING", "nullable": True, "null_count": 1, "unique_count": 4, "null_rate": 0.2, "unique_ratio": 0.8, "mean": None, "outlier_rate": None},
    ]
    issues = detect_schema_drift(baseline, current, baseline_row_count=5, current_row_count=5)
    types = [i["issue_type"] for i in issues]
    # Might still have some similarity but should be low confidence; check that candidate not present or low confidence
    # Our threshold 0.60 and name_sim <0.4 filters, so product_price vs customer_id should be filtered
    assert "COLUMN_RENAMED_CANDIDATE" not in types

def test_rename_candidate_drift_already_type_changed():
    # Type changed column should not be considered rename; but if removed+added with same type family should
    baseline = [
        {"column_name": "discount", "data_type": "FLOAT", "nullable": False, "null_count": 0, "unique_count": 5, "null_rate": 0.0, "unique_ratio": 0.6, "mean": 0.05, "outlier_rate": 0.0},
    ]
    current = [
        {"column_name": "discount_rate", "data_type": "FLOAT", "nullable": False, "null_count": 0, "unique_count": 5, "null_rate": 0.0, "unique_ratio": 0.6, "mean": 0.06, "outlier_rate": 0.0},
    ]
    issues = detect_schema_drift(baseline, current)
    cand = [i for i in issues if i["issue_type"] == "COLUMN_RENAMED_CANDIDATE"]
    assert len(cand) == 1
    assert cand[0]["metadata"]["confidence"] >= 0.75  # likely due to high name sim and same type

def test_schema_history_and_compare_endpoints():
    # Upload two datasets with same logical prefix to test history
    csv_v1 = b"order_id,order_value,discount\n1,100.0,0.05\n2,200.0,0.10\n"
    csv_v2 = b"order_id,order_amount,discount\n1,100.0,0.05\n2,200.0,0.10\n"
    res = client.post("/api/datasets/upload", files={"file": ("orders_test_v1.csv", csv_v1, "text/csv")}, data={"dataset_name": "orders_test_hist"})
    assert res.status_code == 200
    v1_id = res.json()["dataset_id"]
    res = client.post("/api/datasets/upload", files={"file": ("orders_test_v2.csv", csv_v2, "text/csv")}, data={"dataset_name": "orders_test_hist"})
    assert res.status_code == 200
    v2_id = res.json()["dataset_id"]
    # List schemas for v1
    res = client.get(f"/api/datasets/{v1_id}/schemas")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["fingerprint"] is not None
    # History logical
    res = client.get(f"/api/datasets/{v1_id}/schema/history")
    assert res.status_code == 200
    data = res.json()
    assert "physical_history" in data
    assert "logical_evolution" in data
    assert len(data["logical_evolution"]) == 2
    assert data["logical_evolution"][0]["dataset_name"] == "orders_test_hist"
    # Compare
    res = client.get(f"/api/datasets/{v2_id}/schema/compare?baseline_dataset_id={v1_id}")
    assert res.status_code == 200
    comp = res.json()
    assert "drift_issues" in comp
    assert "rename_candidates" in comp
    assert any(i["issue_type"] == "COLUMN_RENAMED_CANDIDATE" for i in comp["drift_issues"])
    assert len(comp["rename_candidates"]) == 1
    # Ensure scan also gets rename candidate
    res = client.post(f"/api/datasets/{v2_id}/scan?baseline_dataset_id={v1_id}")
    assert res.status_code == 200
    scan_id = res.json()["id"]
    res = client.get(f"/api/scans/{scan_id}/issues")
    issues = res.json()
    assert any(i["issue_type"] == "COLUMN_RENAMED_CANDIDATE" for i in issues)
    # Score should have schema_stability dimension affected but not heavily penalized (INFO)
    res = client.get(f"/api/scans/{scan_id}/score")
    assert res.status_code == 200
    score = res.json()
    # schema_stability should be 100 or close because candidate is INFO not penalized
    # But COLUMN_REMOVED is CRITICAL -> schema_stability penalized
    assert score["dimensions"]["schema_stability"]["score"] < 100

def test_real_sample_rename():
    import os, pathlib
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sample_dir = os.path.abspath(os.path.join(current_dir, "../../../sample-data"))
    v1_path = os.path.join(sample_dir, "orders_v1.csv")
    v2_path = os.path.join(sample_dir, "orders_v2_schema_drift.csv")
    # Use upload via API
    with open(v1_path, "rb") as f:
        res = client.post("/api/datasets/upload", files={"file": ("orders_v1.csv", f, "text/csv")})
        assert res.status_code == 200
        v1_id = res.json()["dataset_id"]
    with open(v2_path, "rb") as f:
        res = client.post("/api/datasets/upload", files={"file": ("orders_v2.csv", f, "text/csv")})
        assert res.status_code == 200
        v2_id = res.json()["dataset_id"]
    res = client.get(f"/api/datasets/{v2_id}/schema/compare?baseline_dataset_id={v1_id}")
    comp = res.json()
    # orders_v2 has order_value removed, order_amount added -> should be candidate
    cand = [c for c in comp["rename_candidates"] if c["metadata"]["from_column"] == "order_value"]
    assert len(cand) == 1
    assert cand[0]["metadata"]["to_column"] == "order_amount"
