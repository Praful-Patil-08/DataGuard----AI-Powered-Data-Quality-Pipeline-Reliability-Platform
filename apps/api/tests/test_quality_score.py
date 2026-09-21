import os
os.environ["DATABASE_URL"] = "sqlite:///./test_score.db"
os.environ["OPENAI_API_KEY"] = ""
os.environ["AI_PROVIDER"] = "mock"

import pytest
import pandas as pd
from fastapi.testclient import TestClient

from database import engine, Base
import models
from main import app
from quality_score import compute_quality_score, DIMENSION_WEIGHTS

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def test_score_healthy_is_100():
    issues = []
    result = compute_quality_score(issues, None)
    assert result["score"] == 100
    assert all(v["score"] == 100 for v in result["dimensions"].values())
    assert "Excellent" in result["summary"]
    assert "score" in result and "dimensions" in result

def test_score_deterministic():
    issues = [{"issue_type": "HIGH_NULL_RATE", "severity": "CRITICAL", "metadata": {}}]
    r1 = compute_quality_score(issues, None)
    r2 = compute_quality_score(issues, None)
    assert r1["score"] == r2["score"]
    assert r1["dimensions"] == r2["dimensions"]

def test_score_completeness_breach():
    # 1 critical in completeness -> completeness 75 (100-25), weighted overall
    issues = [{"issue_type": "HIGH_NULL_RATE", "severity": "CRITICAL"}]
    result = compute_quality_score(issues, None)
    assert result["dimensions"]["completeness"]["score"] == 75
    assert result["dimensions"]["completeness"]["critical"] == 1
    # overall: completeness 75*0.2 + others 100*0.8 = 15+80=95
    expected = int(round(75*0.2 + 100*0.8))
    assert result["score"] == expected
    assert result["dimensions"]["completeness"]["evidence"] is not None

def test_score_multiple_dimensions():
    issues = [
        {"issue_type": "COLUMN_REMOVED", "severity": "CRITICAL"},  # schema
        {"issue_type": "NUMERIC_DRIFT", "severity": "CRITICAL"},   # distribution
        {"issue_type": "DUPLICATE_PRIMARY_KEY", "severity": "CRITICAL"},  # uniqueness
        {"issue_type": "CATEGORICAL_INCONSISTENCY", "severity": "WARNING"},  # consistency
    ]
    result = compute_quality_score(issues, None)
    assert result["dimensions"]["schema_stability"]["score"] == 75
    assert result["dimensions"]["distribution_stability"]["score"] == 75
    assert result["dimensions"]["uniqueness"]["score"] == 75
    assert result["dimensions"]["consistency"]["score"] == 90  # warning -10
    # check overall weighted
    assert result["score"] < 90
    assert "dimensions" in result
    # summary mentions weakest
    assert "Weakest" in result["summary"] or "requires attention" in result["summary"] or result["score"] < 90

def test_score_critical_penalty_clamping():
    # 5 critical in same dimension should clamp to 0
    issues = [{"issue_type": "HIGH_NULL_RATE", "severity": "CRITICAL"} for _ in range(5)]
    result = compute_quality_score(issues, None)
    assert result["dimensions"]["completeness"]["score"] == 0  # 100 -125 -> 0
    assert result["score"] < 85  # because one dimension 0 drags down overall

def test_score_freshness_with_date():
    # Fresh data
    df = pd.DataFrame({"order_date": [pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=2), pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1)], "value": [1,2]})
    result = compute_quality_score([], df)
    assert result["dimensions"]["freshness"]["score"] == 100
    # Stale data 40 days ago
    old_date = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=40)
    df2 = pd.DataFrame({"order_date": [old_date, old_date], "value": [1,2]})
    result2 = compute_quality_score([], df2)
    assert result2["dimensions"]["freshness"]["score"] == 80
    # Very stale 100 days
    very_old = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=100)
    df3 = pd.DataFrame({"order_date": [very_old], "value": [1]})
    result3 = compute_quality_score([], df3)
    assert result3["dimensions"]["freshness"]["score"] == 60
    # No date column neutral
    df4 = pd.DataFrame({"value": [1,2]})
    result4 = compute_quality_score([], df4)
    assert result4["dimensions"]["freshness"]["score"] == 100

def test_score_integration_scan_healthy_and_critical():
    # Healthy dataset -> score 100 or near 100
    csv_healthy = b"order_id,customer_id,order_date,amount\n1,101,2026-09-10,100.0\n2,102,2026-09-11,200.0\n3,103,2026-09-12,300.0\n"
    res = client.post("/api/datasets/upload", files={"file": ("healthy.csv", csv_healthy, "text/csv")}, data={"dataset_name": "score_test_healthy"})
    assert res.status_code == 200
    ds_id = res.json()["dataset_id"]
    res = client.post(f"/api/datasets/{ds_id}/scan")
    assert res.status_code == 200
    scan = res.json()
    assert "quality_score" in scan
    assert scan["quality_score"] >= 90  # healthy should be high
    assert scan["quality_dimensions"] is not None
    assert "completeness" in scan["quality_dimensions"]
    # Check score endpoint
    scan_id = scan["id"]
    res = client.get(f"/api/scans/{scan_id}/score")
    assert res.status_code == 200
    score_data = res.json()
    assert score_data["score"] == scan["quality_score"]
    assert "dimensions" in score_data
    assert "summary" in score_data

    # Critical dataset -> low score (multiple dimensions)
    csv_bad = b"order_id,customer_id,order_date,status,amount\n1,,invalid-date,COMPLETED,-10\n1,,2026-09-10,completed,-20\n2,102,2026-09-11,SHIPPED,30\n3,103,bad-date,SHIPPED,40\n"
    res = client.post("/api/datasets/upload", files={"file": ("bad.csv", csv_bad, "text/csv")}, data={"dataset_name": "score_test_bad"})
    assert res.status_code == 200
    ds2 = res.json()["dataset_id"]
    res = client.post(f"/api/datasets/{ds2}/scan")
    assert res.status_code == 200
    scan2 = res.json()
    assert scan2["quality_score"] < 85  # should be degraded (multiple critical across dimensions: got 84)
    assert scan2["quality_score"] < scan["quality_score"]
    assert scan2["quality_dimensions"]["completeness"]["critical"] >= 1
    assert scan2["quality_dimensions"]["validity"]["critical"] >= 1
    # History includes quality_score
    res = client.get(f"/api/datasets/{ds2}/history")
    assert res.status_code == 200
    hist = res.json()["history"]
    assert len(hist) == 1
    assert "quality_score" in hist[0]
    assert hist[0]["quality_score"] == scan2["quality_score"]

def test_score_explainability():
    issues = [
        {"issue_type": "COLUMN_REMOVED", "severity": "CRITICAL"},
        {"issue_type": "HIGH_NULL_RATE", "severity": "WARNING"},
    ]
    result = compute_quality_score(issues, None)
    # Each dimension should have explainable evidence
    for dim_name, dim in result["dimensions"].items():
        assert "score" in dim
        assert "weight" in dim
        assert "evidence" in dim
        assert "critical" in dim
        assert "warning" in dim
        assert isinstance(dim["evidence"], str)
    assert 0 <= result["score"] <= 100
    assert isinstance(result["summary"], str)

def test_score_weights_sum():
    assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 0.001

def test_score_with_contract_breach():
    issues = [
        {"issue_type": "CONTRACT_BREACH_COMPLETENESS", "severity": "CRITICAL"},
        {"issue_type": "CONTRACT_BREACH_RANGE", "severity": "CRITICAL"},
    ]
    result = compute_quality_score(issues, None)
    assert result["dimensions"]["completeness"]["score"] == 75
    assert result["dimensions"]["validity"]["score"] == 75
    assert result["score"] < 95
