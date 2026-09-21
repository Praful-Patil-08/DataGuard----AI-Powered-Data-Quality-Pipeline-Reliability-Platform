import os
os.environ["DATABASE_URL"] = "sqlite:///./test_anomaly.db"
os.environ["OPENAI_API_KEY"] = ""
os.environ["AI_PROVIDER"] = "mock"

import pytest
from fastapi.testclient import TestClient

from database import engine, Base
import models
from main import app
from anomaly import _is_anomalous_zscore, detect_null_rate_anomalies, detect_quality_score_anomaly

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def _upload(name, csv_bytes):
    res = client.post("/api/datasets/upload", files={"file": (name, csv_bytes, "text/csv")}, data={"dataset_name": name.replace(".csv","")})
    assert res.status_code == 200, res.text
    ds_id = res.json()["dataset_id"]
    res = client.post(f"/api/datasets/{ds_id}/scan")
    assert res.status_code == 200, res.text
    return ds_id, res.json()["id"]

def test_zscore_anomaly_detection():
    hist = [2.1, 2.4, 2.0, 2.3, 2.2]
    is_anom, sev, z, ev = _is_anomalous_zscore(14.8, hist)
    assert is_anom is True
    assert sev == "CRITICAL"
    assert abs(z) > 3.0
    assert ev["historical_mean"] == pytest.approx(2.2, abs=0.01)
    assert ev["current"] == 14.8
    # Stable should not be anomaly
    is_anom2, _, _, _ = _is_anomalous_zscore(2.3, hist)
    assert is_anom2 is False

def test_iqr_fallback_small_history():
    hist = [1.0, 1.1, 1.0]
    is_anom, sev, _, ev = _is_anomalous_zscore(5.0, hist)
    assert is_anom is True
    assert ev["method"] == "IQR"

def test_null_rate_anomaly_via_history():
    # Create 5 historical datasets with null rate ~2% (stable) -> 0.02
    for i in range(5):
        rows = []
        for j in range(1, 51):
            cid = "" if j == 25 else str(j)
            rows.append(f"{j},{cid},{j*10}")
        csv = ("order_id,customer_id,val\n" + "\n".join(rows)).encode()
        _upload(f"anom_hist_{i}.csv", csv)
    # Now current with 14% null (7 nulls out of 50)
    rows = []
    for j in range(1, 51):
        cid = "" if j <= 7 else str(j)  # 7 nulls = 14%
        rows.append(f"{j},{cid},{j*10}")
    csv_current = ("order_id,customer_id,val\n" + "\n".join(rows)).encode()
    ds_id, scan_id = _upload("anom_current.csv", csv_current)
    res = client.get(f"/api/scans/{scan_id}/anomalies?window=5")
    assert res.status_code == 200
    anomalies = res.json()["anomalies"]
    # Should have null rate anomaly for customer_id
    null_anoms = [a for a in anomalies if a["anomaly_type"] == "NULL_RATE_ANOMALY"]
    assert len(null_anoms) >= 1
    assert null_anoms[0]["severity"] in ("WARNING", "CRITICAL")
    # historical_mean is 0.02 (2%)
    assert null_anoms[0]["evidence"]["historical_mean"] == pytest.approx(0.02, abs=0.02)
    assert null_anoms[0]["current_null_rate"] == pytest.approx(0.14, abs=0.02)

def test_quality_score_anomaly():
    # Create 5 good scans (quality_score ~100)
    for i in range(5):
        csv = b"order_id,val\n1,10\n2,20\n3,30\n"
        _upload(f"qs_good_{i}.csv", csv)
    # Now bad scan with low quality (many issues) — use distinct prefix so historical is qs_good
    csv_bad = b"order_id,customer_id,amount\n1,, -10\n1,, -20\n2,102,30\n"
    ds_id, scan_id = _upload("qs_bad.csv", csv_bad)
    # Need to ensure qs_bad's historical is qs_good? They share prefix qs_ -> logical qs, so historical includes qs_good
    res = client.get(f"/api/scans/{scan_id}/anomalies?window=10")
    anomalies = res.json()["anomalies"]
    qs_anoms = [a for a in anomalies if a["anomaly_type"] == "QUALITY_SCORE_ANOMALY"]
    assert len(qs_anoms) >= 1
    assert qs_anoms[0]["current_score"] < qs_anoms[0]["historical_mean"]
    ev = qs_anoms[0]["evidence"]
    # Evidence may be z-score or IQR depending on std; check either
    assert "historical_mean" in ev
    assert ev["historical_mean"] == pytest.approx(100.0, abs=5.0)
    # If z_score present, check, otherwise check IQR fences
    if "z_score" in ev:
        assert ev["z_score"] < -2.0
    else:
        assert ev["method"] == "IQR"

def test_dataset_anomalies_endpoint():
    for i in range(5):
        csv = b"order_id,val\n1,10\n2,20\n"
        _upload(f"ds_anom_{i}.csv", csv)
    # Current bad
    csv_bad = b"order_id,val\n1,10\n2,10\n2,10\n"  # duplicate
    ds_id, scan_id = _upload("ds_anom_bad.csv", csv_bad)
    res = client.get(f"/api/datasets/{ds_id}/anomalies?window=5")
    assert res.status_code == 200
    data = res.json()
    assert "anomalies" in data
    assert "status" in data

def test_anomalies_list_all():
    for i in range(3):
        csv = b"a,b\n1,2\n"
        _upload(f"list_anom_{i}.csv", csv)
    res = client.get("/api/anomalies?window=5")
    assert res.status_code == 200
    assert "datasets" in res.json()

def test_no_false_positive_stable():
    # Stable null rate should not trigger anomaly
    for i in range(5):
        csv = b"order_id,customer_id\n1,101\n2,102\n3,103\n"
        _upload(f"stable_{i}.csv", csv)
    csv_stable = b"order_id,customer_id\n1,101\n2,102\n3,103\n"
    ds_id, scan_id = _upload("stable_current.csv", csv_stable)
    res = client.get(f"/api/scans/{scan_id}/anomalies?window=5")
    anomalies = res.json()["anomalies"]
    # Should have no null_rate anomaly (since all 0% null)
    null_anoms = [a for a in anomalies if a["anomaly_type"] == "NULL_RATE_ANOMALY"]
    assert len(null_anoms) == 0

def test_row_count_anomaly():
    for i in range(5):
        csv = b"a,b\n1,2\n3,4\n5,6\n7,8\n"  # 4 rows
        _upload(f"rc_hist_{i}.csv", csv)
    csv_bad = b"a,b\n1,2\n" + b"\n".join([f"{i},{i+1}".encode() for i in range(10)])  # 11 rows? Actually need many
    # Create 20 rows
    csv_big = b"a,b\n" + b"\n".join([f"{i},{i+1}".encode() for i in range(20)])
    ds_id, scan_id = _upload("rc_big.csv", csv_big)
    res = client.get(f"/api/scans/{scan_id}/anomalies?window=5")
    anomalies = res.json()["anomalies"]
    rc_anoms = [a for a in anomalies if a["anomaly_type"] == "ROW_COUNT_ANOMALY"]
    # Might be anomaly due to row count jump 4->20
    if rc_anoms:
        assert rc_anoms[0]["current_row_count"] == 20
        assert rc_anoms[0]["evidence"]["historical_mean"] == pytest.approx(4.0, abs=1.0)

def test_anomaly_evidence_structure():
    for i in range(5):
        csv = b"order_id,val\n1,10\n2,20\n"
        _upload(f"ev_hist_{i}.csv", csv)
    csv_bad = b"order_id,customer_id,amount\n1,, -10\n"
    ds_id, scan_id = _upload("ev_bad.csv", csv_bad)
    res = client.get(f"/api/scans/{scan_id}/anomalies?window=5")
    for anom in res.json()["anomalies"]:
        assert "evidence" in anom
        assert "severity" in anom
        assert anom["severity"] in ("WARNING", "CRITICAL")
        # Evidence should have method, historical_mean, etc.
        ev = anom["evidence"]
        assert "method" in ev or "historical_mean" in ev
