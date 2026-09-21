import os
os.environ["DATABASE_URL"] = "sqlite:///./test_contracts.db"
os.environ["OPENAI_API_KEY"] = ""
os.environ["AI_PROVIDER"] = "mock"

import pytest
import pandas as pd
from fastapi.testclient import TestClient

from database import engine, Base
import models
from main import app
import quality_contracts as qc
from quality_contracts import evaluate_contracts, get_contracts_for_dataset

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def test_contract_crud_and_versioning():
    # Create
    payload = {
        "dataset_name": "orders",
        "column_name": "customer_id",
        "contract_type": "completeness",
        "threshold": 0.99,
        "severity": "CRITICAL",
        "description": "customer_id must not be null >=99%",
        "params": {}
    }
    res = client.post("/api/contracts", json=payload)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["dataset_name"] == "orders"
    assert data["version"] == 1
    assert data["contract_type"] == "completeness"
    cid = data["id"]

    # List
    res = client.get("/api/contracts?dataset_name=orders")
    assert res.status_code == 200
    assert len(res.json()) == 1

    # Update -> version bump
    res = client.put(f"/api/contracts/{cid}", json={"threshold": 0.995, "severity": "WARNING"})
    assert res.status_code == 200
    assert res.json()["version"] == 2
    assert res.json()["threshold"] == 0.995

    # Get single
    res = client.get(f"/api/contracts/{cid}")
    assert res.status_code == 200
    assert res.json()["id"] == cid

    # Delete
    res = client.delete(f"/api/contracts/{cid}")
    assert res.status_code == 200
    res = client.get(f"/api/contracts/{cid}")
    assert res.status_code == 404

def test_contract_validation():
    # Invalid type
    res = client.post("/api/contracts", json={"dataset_name": "orders", "column_name": "x", "contract_type": "invalid", "threshold": 0.9})
    assert res.status_code == 400
    # Invalid threshold
    res = client.post("/api/contracts", json={"dataset_name": "orders", "column_name": "x", "contract_type": "completeness", "threshold": 1.5})
    assert res.status_code == 400
    # Missing dataset_name
    res = client.post("/api/contracts", json={"dataset_name": "", "column_name": "x", "contract_type": "completeness", "threshold": 0.9})
    assert res.status_code == 400
    # Range without params
    res = client.post("/api/contracts", json={"dataset_name": "orders", "column_name": "amount", "contract_type": "range", "threshold": 0.99, "params": {}})
    assert res.status_code == 400

def test_evaluate_completeness_breach():
    from database import SessionLocal
    db = SessionLocal()
    # Create contract: customer_id >=99% complete
    contract = qc.create_contract(db, {
        "dataset_name": "orders",
        "column_name": "customer_id",
        "contract_type": "completeness",
        "threshold": 0.99,
        "params": {},
        "severity": "CRITICAL",
        "description": "test"
    })
    df = pd.DataFrame({"customer_id": [1, None, None, 2, 3], "order_id": [1,2,3,4,5]})
    # 2/5 null = 40% null => 60% complete <99% => breach
    breaches = evaluate_contracts(df, "orders_v1", [contract])
    assert len(breaches) == 1
    assert breaches[0]["issue_type"] == "CONTRACT_BREACH_COMPLETENESS"
    assert breaches[0]["severity"] == "CRITICAL"
    assert breaches[0]["metadata"]["contract_id"] == contract.id
    assert breaches[0]["metadata"]["actual_completeness"] == 0.6
    assert "version" in breaches[0]["metadata"]
    db.close()

def test_evaluate_uniqueness_breach():
    from database import SessionLocal
    db = SessionLocal()
    contract = qc.create_contract(db, {
        "dataset_name": "orders",
        "column_name": "order_id",
        "contract_type": "uniqueness",
        "threshold": 1.0,
        "severity": "CRITICAL"
    })
    df = pd.DataFrame({"order_id": [1,2,2,3]})
    breaches = evaluate_contracts(df, "orders", [contract])
    assert len(breaches) == 1
    assert breaches[0]["issue_type"] == "CONTRACT_BREACH_UNIQUENESS"
    assert breaches[0]["metadata"]["duplicate_count"] == 1
    # Healthy case: unique
    df2 = pd.DataFrame({"order_id": [1,2,3,4]})
    breaches2 = evaluate_contracts(df2, "orders", [contract])
    assert len(breaches2) == 0
    db.close()

def test_evaluate_range_breach():
    from database import SessionLocal
    db = SessionLocal()
    contract = qc.create_contract(db, {
        "dataset_name": "orders",
        "column_name": "amount",
        "contract_type": "range",
        "threshold": 0.995,
        "params": {"min": 0},
        "severity": "CRITICAL"
    })
    # 1 negative out of 5 => 80% valid <99.5% => breach
    df = pd.DataFrame({"amount": [10, -5, 20, 30, 40]})
    breaches = evaluate_contracts(df, "orders", [contract])
    assert len(breaches) == 1
    assert breaches[0]["issue_type"] == "CONTRACT_BREACH_RANGE"
    assert breaches[0]["metadata"]["invalid_count"] == 1
    # Healthy: all positive
    df2 = pd.DataFrame({"amount": [10,20,30,40,50]})
    assert len(evaluate_contracts(df2, "orders", [contract])) == 0
    db.close()

def test_evaluate_regex_breach():
    from database import SessionLocal
    db = SessionLocal()
    contract = qc.create_contract(db, {
        "dataset_name": "orders",
        "column_name": "status",
        "contract_type": "regex",
        "threshold": 1.0,
        "params": {"pattern": "^(COMPLETED|SHIPPED|PENDING)$"},
        "severity": "WARNING"
    })
    df = pd.DataFrame({"status": ["COMPLETED", "bad_value", "SHIPPED"]})
    breaches = evaluate_contracts(df, "orders", [contract])
    assert len(breaches) == 1
    assert breaches[0]["issue_type"] == "CONTRACT_BREACH_REGEX"
    assert breaches[0]["metadata"]["mismatch_count"] == 1
    db.close()

def test_evaluate_row_count_breach():
    from database import SessionLocal
    db = SessionLocal()
    contract = qc.create_contract(db, {
        "dataset_name": "orders",
        "column_name": None,
        "contract_type": "row_count",
        "params": {"min": 5, "max": 100},
        "severity": "WARNING"
    })
    df_small = pd.DataFrame({"a": [1,2]})
    breaches = evaluate_contracts(df_small, "orders", [contract])
    assert len(breaches) == 1
    assert breaches[0]["issue_type"] == "CONTRACT_BREACH_ROW_COUNT"
    df_ok = pd.DataFrame({"a": [1,2,3,4,5,6]})
    assert len(evaluate_contracts(df_ok, "orders", [contract])) == 0
    db.close()

def test_contract_prefix_matching():
    from database import SessionLocal
    db = SessionLocal()
    qc.create_contract(db, {"dataset_name": "orders", "column_name": "customer_id", "contract_type": "completeness", "threshold": 0.99})
    qc.create_contract(db, {"dataset_name": "customers", "column_name": "customer_id", "contract_type": "completeness", "threshold": 0.99})
    # orders_v1 should match orders but not customers
    matched = get_contracts_for_dataset(db, "orders_v1")
    assert len(matched) == 1
    assert matched[0].dataset_name == "orders"
    # orders_bad_quality matches orders
    matched2 = get_contracts_for_dataset(db, "orders_bad_quality")
    assert len(matched2) == 1
    db.close()

def test_contract_scan_integration():
    # Create dataset orders_v1
    import pathlib
    csv = b"order_id,customer_id,amount\n1,101,10.0\n2,102,20.0\n3,103,30.0\n4,,40.0\n"
    # Upload
    res = client.post("/api/datasets/upload", files={"file": ("orders_v1.csv", csv, "text/csv")}, data={"dataset_name": "orders"})
    assert res.status_code == 200, res.text
    ds_id = res.json()["dataset_id"]
    # Also need to check dataset name is prefix matched: uploaded name defaults to file prefix "orders_v1" -> our contract dataset_name "orders" should match
    # Create contracts before scan
    client.post("/api/contracts", json={"dataset_name": "orders", "column_name": "customer_id", "contract_type": "completeness", "threshold": 0.99, "severity": "CRITICAL"})
    client.post("/api/contracts", json={"dataset_name": "orders", "column_name": "amount", "contract_type": "range", "threshold": 1.0, "params": {"min": 0}, "severity": "CRITICAL"})
    client.post("/api/contracts", json={"dataset_name": "orders", "column_name": "order_id", "contract_type": "uniqueness", "threshold": 1.0, "severity": "CRITICAL"})
    # Scan
    res = client.post(f"/api/datasets/{ds_id}/scan")
    assert res.status_code == 200
    scan_id = res.json()["id"]
    # Fetch issues: should include contract breach for customer_id (1/4 null => 75% complete <99%)
    res = client.get(f"/api/scans/{scan_id}/issues")
    issues = res.json()
    types = [i["issue_type"] for i in issues]
    assert "CONTRACT_BREACH_COMPLETENESS" in types
    # Check explainability metadata
    breach = next(i for i in issues if i["issue_type"] == "CONTRACT_BREACH_COMPLETENESS")
    assert breach["column_name"] == "customer_id"
    assert "expected_completeness" in breach["metadata"] or "threshold" in breach["metadata"]
    # Verify dataset contracts endpoint
    res = client.get(f"/api/datasets/{ds_id}/contracts")
    assert res.status_code == 200
    assert len(res.json()) == 3

def test_contract_disabled_not_evaluated():
    from database import SessionLocal
    db = SessionLocal()
    contract = qc.create_contract(db, {"dataset_name": "orders", "column_name": "customer_id", "contract_type": "completeness", "threshold": 1.0, "severity": "CRITICAL"})
    # disable
    db2 = SessionLocal()
    qc.update_contract(db2, contract.id, {"enabled": False})
    db2.close()
    # fetch only enabled should be 0
    enabled = get_contracts_for_dataset(db, "orders", only_enabled=True)
    assert len(enabled) == 0
    # disabled still exists if we query without filter? Our get_contracts_for_dataset filters enabled True by default
    df = pd.DataFrame({"customer_id": [None, None]})
    breaches = evaluate_contracts(df, "orders", enabled)
    assert len(breaches) == 0
    db.close()

def test_contract_separate_from_scan_results():
    # Ensure contracts table is separate from issues; contract creation does not create Issue
    res = client.post("/api/contracts", json={"dataset_name": "orders", "column_name": "amount", "contract_type": "range", "threshold": 0.9, "params": {"min": 0}})
    assert res.status_code == 200
    contract_id = res.json()["id"]
    # No scan yet, no issues
    from database import SessionLocal
    db = SessionLocal()
    issues_count = db.query(models.Issue).count()
    contracts_count = db.query(models.QualityContract).count()
    assert contracts_count == 1
    assert issues_count == 0
    db.close()

def test_evaluate_missing_column():
    from database import SessionLocal
    db = SessionLocal()
    contract = qc.create_contract(db, {"dataset_name": "orders", "column_name": "nonexistent", "contract_type": "completeness", "threshold": 0.99})
    df = pd.DataFrame({"order_id": [1,2,3]})
    breaches = evaluate_contracts(df, "orders", [contract])
    assert len(breaches) == 1
    assert breaches[0]["metadata"]["reason"] == "column_not_found"
    db.close()

def test_api_evaluate_endpoint():
    csv = b"order_id,amount\n1,10\n2,-5\n3,20\n"
    res = client.post("/api/datasets/upload", files={"file": ("test_eval.csv", csv, "text/csv")}, data={"dataset_name": "test_eval"})
    ds_id = res.json()["dataset_id"]
    client.post("/api/contracts", json={"dataset_name": "test_eval", "column_name": "amount", "contract_type": "range", "threshold": 1.0, "params": {"min": 0}, "severity": "CRITICAL"})
    res = client.post(f"/api/datasets/{ds_id}/contracts/evaluate")
    assert res.status_code == 200
    assert res.json()["contracts_evaluated"] == 1
    assert len(res.json()["breaches"]) == 1
    assert res.json()["breaches"][0]["issue_type"] == "CONTRACT_BREACH_RANGE"
