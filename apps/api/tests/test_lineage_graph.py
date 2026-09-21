import os
os.environ["DATABASE_URL"] = "sqlite:///./test_lineage_graph.db"
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

def test_seed_and_direct_downstream():
    # First call should seed from lineage_config.json
    res = client.get("/api/lineage/edges")
    assert res.status_code == 200
    edges = res.json()
    assert len(edges) >= 7  # seeded 7+ edges from DEFAULT_LINEAGE_MAP
    # Check direct downstream for orders.order_value (seeded, still demo)
    res = client.get("/api/lineage/orders/order_value")
    assert res.status_code == 200
    data = res.json()
    assert data["is_demo"] is True  # seeded demo lineage (DB-backed but still demo until custom production lineage)
    assert len(data["affected_assets"]) >= 2
    names = [a["name"] for a in data["affected_assets"]]
    assert "revenue_model" in names

def test_create_and_list_edges():
    payload = {
        "source_dataset": "orders",
        "source_column": "order_id",
        "target_dataset": "orders_enriched",
        "target_column": None,
        "target_type": "DATASET",
        "job_name": "enrichment_job",
        "relationship": "DIRECT"
    }
    res = client.post("/api/lineage/edges", json=payload)
    assert res.status_code == 200, res.text
    edge = res.json()
    assert edge["source_dataset"] == "orders"
    assert edge["source_column"] == "order_id"
    assert edge["target_dataset"] == "orders_enriched"
    assert edge["job_name"] == "enrichment_job"
    # List with filter
    res = client.get("/api/lineage/edges?source_dataset=orders")
    assert res.status_code == 200
    assert len([e for e in res.json() if e["source_dataset"] == "orders"]) >= 1
    # Delete
    res = client.delete(f"/api/lineage/edges/{edge['id']}")
    assert res.status_code == 200
    res = client.get("/api/lineage/edges?source_dataset=orders&source_column=order_id")
    assert all(e["id"] != edge["id"] for e in res.json())

def test_column_and_dataset_level_lineage():
    # Column-level
    res = client.post("/api/lineage/edges", json={
        "source_dataset": "events",
        "source_column": "user_id",
        "target_dataset": "user_360",
        "target_type": "DATASET",
        "relationship": "JOIN_KEY"
    })
    assert res.status_code == 200
    # Dataset-level (no column)
    res = client.post("/api/lineage/edges", json={
        "source_dataset": "events",
        "source_column": None,
        "target_dataset": "events_staging",
        "target_type": "DATASET",
        "relationship": "STAGING"
    })
    assert res.status_code == 200
    # Query column-level
    res = client.get("/api/lineage/events/user_id")
    assert res.status_code == 200
    assert any(a["name"] == "user_360" for a in res.json()["affected_assets"])
    # Query dataset-level downstream
    res = client.get("/api/lineage/events/downstream")
    assert res.status_code == 200
    data = res.json()
    assert data["node_count"] >= 2

def test_graph_traversal_chain():
    # Create chain: A -> B -> C -> D
    client.post("/api/lineage/edges", json={"source_dataset": "dataset_a", "source_column": "col1", "target_dataset": "dataset_b", "target_type": "DATASET", "job_name": "job1"})
    client.post("/api/lineage/edges", json={"source_dataset": "dataset_b", "target_dataset": "dataset_c", "target_type": "DATASET", "job_name": "job2"})
    client.post("/api/lineage/edges", json={"source_dataset": "dataset_c", "target_dataset": "dataset_d", "target_type": "DATASET", "job_name": "job3"})
    # Traverse from A col1 depth 3 should reach D
    res = client.get("/api/lineage/dataset_a/downstream?column=col1&depth=3")
    assert res.status_code == 200
    data = res.json()
    assert data["node_count"] >= 4
    assert data["edge_count"] >= 3
    # Check nodes include dataset_d
    datasets = [n["dataset"] for n in data["nodes"]]
    assert "dataset_d" in datasets
    # Depth 1 should only reach B
    res = client.get("/api/lineage/dataset_a/downstream?column=col1&depth=1")
    data = res.json()
    assert data["node_count"] == 2  # A and B
    assert data["edge_count"] == 1
    # Upstream from D should reach A
    res = client.get("/api/lineage/dataset_d/upstream?depth=3")
    data = res.json()
    assert any(n["dataset"] == "dataset_a" for n in data["nodes"])

def test_graph_endpoint_both_directions():
    client.post("/api/lineage/edges", json={"source_dataset": "src", "source_column": "id", "target_dataset": "mid", "target_type": "DATASET"})
    client.post("/api/lineage/edges", json={"source_dataset": "mid", "target_dataset": "tgt", "target_type": "DASHBOARD"})
    res = client.get("/api/lineage/graph?dataset=mid&depth=2")
    assert res.status_code == 200
    data = res.json()
    assert "downstream" in data
    assert "upstream" in data
    assert data["dataset"] == "mid"
    assert data["downstream"]["node_count"] >= 1
    assert data["upstream"]["node_count"] >= 1

def test_cycle_protection():
    # Create cycle: X -> Y -> X
    client.post("/api/lineage/edges", json={"source_dataset": "cycle_x", "target_dataset": "cycle_y", "target_type": "DATASET"})
    client.post("/api/lineage/edges", json={"source_dataset": "cycle_y", "target_dataset": "cycle_x", "target_type": "DATASET"})
    res = client.get("/api/lineage/cycle_x/downstream?depth=5")
    assert res.status_code == 200
    data = res.json()
    # Should not infinite loop, node_count <= 2 + maybe start
    assert data["node_count"] <= 5
    assert data["edge_count"] <= 2

def test_lineage_with_job_run():
    res = client.post("/api/lineage/edges", json={
        "source_dataset": "raw_events",
        "source_column": "event_id",
        "target_dataset": "cleaned_events",
        "target_type": "DATASET",
        "job_name": "cleaning_job",
        "run_id": "run_123",
        "relationship": "CLEANED"
    })
    assert res.status_code == 200
    assert res.json()["job_name"] == "cleaning_job"
    assert res.json()["run_id"] == "run_123"
    # List by job
    res = client.get("/api/lineage/edges?job_name=cleaning_job")
    assert len(res.json()) == 1

def test_backward_compat_file_fallback():
    # For unknown dataset/column not in DB, should fallback to heuristic
    res = client.get("/api/lineage/unknown_dataset/unknown_col")
    assert res.status_code == 200
    data = res.json()
    # Should return heuristic assets (at least 1)
    assert len(data["affected_assets"]) >= 1
    # For DB-seeded, is_demo False; for heuristic fallback, may be True? Our enhanced endpoint returns is_demo False for DB, True for file
    # Unknown should be heuristic, so is_demo? Our code returns DB first, but if DB has no edge for that dataset/col, get_direct_downstream returns [], so we fallback to file heuristic and is_demo True
    # Check that fallback returns something
    assert data["column_name"] == "unknown_col"

def test_incident_uses_lineage():
    # Ensure incident downstream uses lineage graph (via get_downstream_impact DB)
    csv = b"order_id,customer_id,order_value\n1,101,100\n2,102,200\n"
    res = client.post("/api/datasets/upload", files={"file": ("lineage_inc.csv", csv, "text/csv")}, data={"dataset_name": "orders"})
    ds_id = res.json()["dataset_id"]
    # Trigger breach on order_value via contract
    client.post("/api/contracts", json={"dataset_name": "orders", "column_name": "order_value", "contract_type": "completeness", "threshold": 1.0, "severity": "CRITICAL"})
    csv_bad = b"order_id,customer_id,order_value\n1,101,\n2,102,200\n"
    res = client.post("/api/datasets/upload", files={"file": ("lineage_inc_bad.csv", csv_bad, "text/csv")}, data={"dataset_name": "orders"})
    bad_id = res.json()["dataset_id"]
    res = client.post(f"/api/datasets/{bad_id}/scan")
    scan_id = res.json()["id"]
    res = client.get(f"/api/scans/{scan_id}/incidents")
    inc = res.json()[0]
    assert len(inc["affected_assets"]) >= 1
    # Should contain revenue_model via lineage
    assert any("revenue" in a.lower() for a in inc["affected_assets"])
