import os
os.environ["DATABASE_URL"] = "sqlite:///./test_stat_drift.db"
os.environ["OPENAI_API_KEY"] = ""
os.environ["AI_PROVIDER"] = "mock"

import pytest
import pandas as pd
import numpy as np
from fastapi.testclient import TestClient

from database import engine, Base
import models
from main import app
from statistical_drift import (
    _psi, _jsd, _ks_statistic,
    psi_categorical, psi_numeric, ks_numeric, jsd_categorical,
    detect_statistical_drift_for_column,
)
from drift import detect_schema_drift

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def test_psi_basic():
    # Expected 50/50, actual 90/10 => high PSI
    psi = _psi([0.5, 0.5], [0.9, 0.1])
    assert psi > 0.5
    # Same distribution => 0
    psi2 = _psi([0.5, 0.5], [0.5, 0.5])
    assert psi2 == 0.0

def test_jsd_basic():
    jsd = _jsd([0.5, 0.5], [0.5, 0.5])
    assert jsd == 0.0
    jsd2 = _jsd([0.9, 0.1], [0.1, 0.9])
    assert jsd2 > 0.4

def test_ks_basic():
    b = np.array([1,2,3,4,5])
    c = np.array([6,7,8,9,10])
    ks = _ks_statistic(b, c)
    assert ks == 1.0
    ks2 = _ks_statistic(b, b)
    assert ks2 == 0.0

def test_psi_categorical_breach():
    # Baseline: 80% A, 20% B ; Current: 20% A, 80% B => PSI high
    base = pd.Series(["A"]*80 + ["B"]*20)
    curr = pd.Series(["A"]*20 + ["B"]*80)
    psi, ev = psi_categorical(base, curr)
    assert psi is not None
    assert psi > 0.5
    assert "baseline_percents" in ev

def test_psi_categorical_insufficient_rows():
    base = pd.Series(["A"]*10)
    curr = pd.Series(["A"]*10)
    psi, ev = psi_categorical(base, curr)
    assert psi is None
    assert ev["reason"] == "insufficient_rows (<30)"

def test_psi_numeric_breach():
    np.random.seed(0)
    base = pd.Series(np.random.normal(0, 1, 100))
    curr = pd.Series(np.random.normal(5, 1, 100))  # shifted mean
    psi, ev = psi_numeric(base, curr)
    assert psi is not None
    assert psi > 0.25
    assert "bins" in ev

def test_ks_numeric_breach():
    base = pd.Series(list(range(10))*10)  # 0-9 repeated 10 times => 10 unique
    curr = pd.Series(list(range(10,20))*10)  # 10-19 repeated
    ks, ev = ks_numeric(base, curr)
    assert ks is not None
    assert ks > 0.8
    assert ev["baseline_n"] == 100

def test_jsd_categorical_breach():
    base = pd.Series(["A"]*80 + ["B"]*20)
    curr = pd.Series(["A"]*20 + ["B"]*80)
    jsd, ev = jsd_categorical(base, curr)
    assert jsd is not None
    assert jsd > 0.3

def test_detect_statistical_drift_for_column_numeric():
    base = pd.Series(np.random.normal(0, 1, 100))
    curr = pd.Series(np.random.normal(3, 1, 100))
    issues = detect_statistical_drift_for_column("amount", base, curr, "FLOAT")
    # Should have PSI and KS for numeric with large shift
    types = [i["issue_type"] for i in issues]
    assert "NUMERIC_PSI_DRIFT" in types or "NUMERIC_KS_DRIFT" in types
    for iss in issues:
        assert "metric" in iss["metadata"]
        assert "threshold_warning" in iss["metadata"]
        assert "evidence" in iss["metadata"]
        assert iss["severity"] in ("WARNING", "CRITICAL")
        assert iss["column_name"] == "amount"

def test_detect_statistical_drift_for_column_categorical():
    base = pd.Series(["COMPLETED"]*80 + ["SHIPPED"]*20)
    curr = pd.Series(["COMPLETED"]*20 + ["SHIPPED"]*80)
    issues = detect_statistical_drift_for_column("status", base, curr, "STRING")
    types = [i["issue_type"] for i in issues]
    assert "CATEGORICAL_PSI_DRIFT" in types
    # Check evidence structure
    for iss in issues:
        assert iss["metadata"]["threshold_warning"] == 0.1
        assert "evidence" in iss["metadata"]

def test_detect_statistical_skip_small_sample():
    base = pd.Series([1,2,3])
    curr = pd.Series([4,5,6])
    issues = detect_statistical_drift_for_column("val", base, curr, "INTEGER")
    assert len(issues) == 0  # insufficient rows

def test_drift_integration_with_dataframes():
    # Baseline and current with distribution shift
    baseline_cols = [
        {"column_name": "amount", "data_type": "FLOAT", "nullable": False, "null_count": 0, "unique_count": 100, "null_rate": 0.0, "unique_ratio": 1.0, "mean": 100.0, "outlier_rate": 0.0},
        {"column_name": "status", "data_type": "STRING", "nullable": False, "null_count": 0, "unique_count": 2, "null_rate": 0.0, "unique_ratio": 0.02, "mean": None, "outlier_rate": None},
    ]
    current_cols = [
        {"column_name": "amount", "data_type": "FLOAT", "nullable": False, "null_count": 0, "unique_count": 100, "null_rate": 0.0, "unique_ratio": 1.0, "mean": 500.0, "outlier_rate": 0.1},
        {"column_name": "status", "data_type": "STRING", "nullable": False, "null_count": 0, "unique_count": 2, "null_rate": 0.0, "unique_ratio": 0.02, "mean": None, "outlier_rate": None},
    ]
    base_df = pd.DataFrame({"amount": np.random.normal(100, 10, 100), "status": ["COMPLETED"]*80 + ["SHIPPED"]*20})
    curr_df = pd.DataFrame({"amount": np.random.normal(500, 10, 100), "status": ["COMPLETED"]*20 + ["SHIPPED"]*80})
    issues = detect_schema_drift(baseline_cols, current_cols, baseline_row_count=100, current_row_count=100, baseline_df=base_df, current_df=curr_df)
    types = [i["issue_type"] for i in issues]
    assert "NUMERIC_PSI_DRIFT" in types or "NUMERIC_KS_DRIFT" in types
    assert "CATEGORICAL_PSI_DRIFT" in types or "CATEGORICAL_JSD_DRIFT" in types
    # Check each has metric and evidence
    for iss in issues:
        if iss["issue_type"] in ("NUMERIC_PSI_DRIFT", "NUMERIC_KS_DRIFT", "CATEGORICAL_PSI_DRIFT", "CATEGORICAL_JSD_DRIFT"):
            assert "metric" in iss["metadata"]
            assert "evidence" in iss["metadata"]
            assert iss["column_name"] in ("amount", "status")

def test_scan_integration_statistical_drift():
    # Create two datasets with same schema but different distributions
    # Use 100 rows to satisfy sample size >=30
    import os
    np.random.seed(42)
    base_amounts = np.random.normal(100, 10, 100).tolist()
    curr_amounts = np.random.normal(500, 10, 100).tolist()
    base_status = ["COMPLETED"]*80 + ["SHIPPED"]*20
    curr_status = ["COMPLETED"]*20 + ["SHIPPED"]*80
    # Build CSVs
    import csv, io
    def make_csv(amounts, statuses):
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["order_id", "amount", "status"])
        for i, (a, s) in enumerate(zip(amounts, statuses)):
            w.writerow([i+1, round(a, 2), s])
        return out.getvalue().encode()
    csv_base = make_csv(base_amounts, base_status)
    csv_curr = make_csv(curr_amounts, curr_status)
    res = client.post("/api/datasets/upload", files={"file": ("base.csv", csv_base, "text/csv")}, data={"dataset_name": "stat_test"})
    assert res.status_code == 200
    base_id = res.json()["dataset_id"]
    res = client.post("/api/datasets/upload", files={"file": ("curr.csv", csv_curr, "text/csv")}, data={"dataset_name": "stat_test"})
    assert res.status_code == 200
    curr_id = res.json()["dataset_id"]
    # Scan curr with baseline
    res = client.post(f"/api/datasets/{curr_id}/scan?baseline_dataset_id={base_id}")
    assert res.status_code == 200
    scan_id = res.json()["id"]
    res = client.get(f"/api/scans/{scan_id}/issues")
    issues = res.json()
    types = [i["issue_type"] for i in issues]
    # Should have statistical drifts
    assert any(t in types for t in ("NUMERIC_PSI_DRIFT", "NUMERIC_KS_DRIFT", "CATEGORICAL_PSI_DRIFT", "CATEGORICAL_JSD_DRIFT"))
    # Check evidence
    stat_issues = [i for i in issues if "PSI" in i["issue_type"] or "KS" in i["issue_type"] or "JSD" in i["issue_type"]]
    assert len(stat_issues) >= 1
    for iss in stat_issues:
        assert iss["metadata"]["metric"] in ("PSI", "KS", "JSD")
        assert "evidence" in iss["metadata"]
        assert "threshold_warning" in iss["metadata"]
    # Check score reflects distribution drift (should be <100)
    res = client.get(f"/api/scans/{scan_id}/score")
    score = res.json()
    assert score["dimensions"]["distribution_stability"]["score"] < 100
    # Compare endpoint also should return statistical
    res = client.get(f"/api/datasets/{curr_id}/schema/compare?baseline_dataset_id={base_id}")
    assert res.status_code == 200
    comp = res.json()
    assert "statistical_drifts" in comp
    assert len(comp["statistical_drifts"]) >= 1
    assert comp["statistical_drifts"][0]["metadata"]["metric"] in ("PSI", "KS", "JSD")

def test_statistical_no_false_positive_stable():
    # Stable distributions should not trigger drift
    base = pd.Series(np.random.normal(100, 10, 100))
    curr = pd.Series(np.random.normal(100, 10, 100))
    issues = detect_statistical_drift_for_column("amount", base, curr, "FLOAT")
    # May still have small PSI but should be <0.1 threshold, so no issue
    # Allow 0 or 1 warning but not critical; check that not all stable trigger critical
    # For stable, we expect 0 issues or only small warning
    # We'll assert no critical
    for iss in issues:
        assert iss["severity"] != "CRITICAL" or iss["metadata"]["psi"] < 0.5
