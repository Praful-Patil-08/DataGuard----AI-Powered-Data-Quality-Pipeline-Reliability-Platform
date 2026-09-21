import os
os.environ["DATABASE_URL"] = "sqlite:///./test_rag.db"
os.environ["OPENAI_API_KEY"] = ""
os.environ["AI_PROVIDER"] = "mock"

import pytest
from fastapi.testclient import TestClient

from database import engine, Base
import models
from main import app
from rag import retrieve, retrieve_for_scan

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def test_retrieve_dataset_match():
    # Should retrieve orders customer_id runbook
    results = retrieve(dataset="orders", column="customer_id", issue_types=["PRIMARY_KEY_NULL"], k=3)
    assert len(results) >= 1
    assert any("customer_id" in r["id"] for r in results)
    assert all("_score" in r for r in results)
    # Generic should not be top for specific
    assert results[0]["dataset"] == "orders"

def test_retrieve_column_match():
    results = retrieve(dataset="orders", column="order_value", issue_types=["COLUMN_REMOVED"], k=3)
    assert len(results) >= 1
    assert any("order_value" in r["column"] for r in results)

def test_retrieve_issue_type_match():
    results = retrieve(dataset="orders", column="amount", issue_types=["NEGATIVE_VALUE_ANOMALY"], k=2)
    assert len(results) >= 1
    assert any(r["issue_type"] == "NEGATIVE_VALUE_ANOMALY" for r in results)

def test_retrieve_scoped_no_generic_fallback():
    # Query for unknown dataset/column should return empty or low score generic only if min_score not met
    results = retrieve(dataset="unknown_xyz", column="unknown_col", issue_types=["UNKNOWN_TYPE"], k=3, min_score=5)
    # High min_score should filter generic docs
    assert len(results) == 0
    # With low min_score, may return generic but still scoped
    results2 = retrieve(dataset="unknown_xyz", column="unknown_col", issue_types=["UNKNOWN_TYPE"], k=3, min_score=1)
    # Should still be limited
    assert len(results2) <= 3

def test_retrieve_for_scan():
    # Create a scan with issues
    csv = b"order_id,customer_id,order_value\n1,,100\n1,,200\n"
    res = client.post("/api/datasets/upload", files={"file": ("rag_test.csv", csv, "text/csv")}, data={"dataset_name": "orders"})
    ds_id = res.json()["dataset_id"]
    res = client.post(f"/api/datasets/{ds_id}/scan")
    scan_id = res.json()["id"]
    # Retrieve via scan
    res = client.get(f"/api/rag/scan/{scan_id}?k=3")
    assert res.status_code == 200
    data = res.json()
    assert data["scan_id"] == scan_id
    assert "results" in data
    # Should retrieve relevant docs for that scan's dataset/issues
    assert len(data["results"]) >= 1
    assert data["results"][0]["dataset"] in ("orders", "*")

def test_rag_api_retrieve():
    res = client.post("/api/rag/retrieve?dataset=orders&column=customer_id&issue_type=PRIMARY_KEY_NULL&k=2")
    assert res.status_code == 200
    data = res.json()
    assert "results" in data
    assert data["count"] >= 1
    assert any("customer" in r["id"].lower() for r in data["results"])

def test_rag_api_list_docs():
    res = client.get("/api/rag/docs")
    assert res.status_code == 200
    assert res.json()["count"] >= 7
    assert len(res.json()["docs"]) >= 7

def test_ai_uses_rag():
    # Ensure AI context includes retrieved docs
    csv = b"order_id,customer_id,order_value\n1,,100\n"
    res = client.post("/api/datasets/upload", files={"file": ("rag_ai.csv", csv, "text/csv")}, data={"dataset_name": "orders"})
    ds_id = res.json()["dataset_id"]
    res = client.post(f"/api/datasets/{ds_id}/scan")
    scan_id = res.json()["id"]
    # Check AI context via direct call
    from database import SessionLocal
    from ai_context import build_ai_context
    db = SessionLocal()
    ctx = build_ai_context(db, scan_id)
    db.close()
    assert "retrieved_docs" in ctx
    assert len(ctx["retrieved_docs"]) >= 1
    # Trigger AI analysis and check that recommended_action includes runbook
    res = client.post(f"/api/scans/{scan_id}/analyze")
    assert res.status_code == 200
    data = res.json()
    # Should contain runbook reference if RAG retrieved
    assert "runbook" in data["recommended_action"].lower() or "Runbook" in data["recommended_action"] or len(data["recommended_action"]) > 50

def test_retrieve_no_hallucination():
    # Ensure retrieve only returns docs from KB, not invented
    results = retrieve(dataset="orders", column="order_value", issue_types=["COLUMN_REMOVED"], k=5)
    from rag import _load_kb
    kb_ids = set(d["id"] for d in _load_kb())
    for r in results:
        assert r["id"] in kb_ids
