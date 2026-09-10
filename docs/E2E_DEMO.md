# E2E Demo — 60-sec Flow (verified with real Olist data + mock AI)

**Prereq:** `cd dataguard/apps/api && source .venv/bin/activate && uvicorn main:app --port 8000` and `cd dataguard/apps/web && npm run dev` (or `docker compose up` when Docker Desktop running).

**Flow (also covered by `pytest tests/test_enhanced.py` + `test_demo`):**

1. **Healthy baseline** `POST /api/datasets/upload` `olist_orders_dataset.csv` (99k rows, 16.8MB) → `GET /api/datasets/{id}/schema` shows `order_value mean 842.594 null_rate 0` → `POST /api/datasets/{id}/scan` → `incident_severity INFO` `healthy 8` → `GET /api/datasets/{id}/history` has 1 entry.

2. **Schema drift** `POST /api/datasets/upload` `olist_orders` drift synthetic (remove `order_value`, add `order_amount`, `discount FLOAT→STRING`) or real `olist_orders_dataset.csv` vs drifted copy → `POST /api/datasets/{v2}/scan?baseline_dataset_id={v1}` → `COLUMN_REMOVED` + `TYPE_CHANGED` + `ROW_COUNT_DRIFT` `incident_summary: Critical incident: columns removed: order_value...` → `GET /api/scans/{id}/gate` → `FAIL` `row-count drop`.

3. **Quality bugs** `olist_order_items_dataset.csv` (112k rows) → `DUPLICATE_PRIMARY_KEY order_id 12%` + `NUMERIC_ANOMALY` → `CRITICAL`.

4. **What it means** `GET /api/scans/{id}` shows `incident_summary` human-friendly (not `COLUMN_REMOVED` code) + `GET /api/lineage/orders/order_value` → `revenue_model` → `Executive Revenue Dashboard` (`is_demo:true`) + `GET /api/dashboard/business-impact` → `Revenue reporting CRITICAL`.

5. **AI Analyst** `POST /api/scans/{id}/analyze` (history-aware, last 3 `orders` prefix) → `summary` + `root_cause` with `Historical context: 2 prior healthy` + `technical_impact` + `business_impact: Revenue reporting at risk…` + `confidence 0.92` + `requires_human_approval:true`. Provider `mock` by default; `AI_PROVIDER=gemini|openai` + key auto-switches (`ai_provider.py`).

6. **Human approval** `POST /api/remediations/{id}/approve` `{"decision_by":"alice@dataguard.test"}` → `APPROVED` → `GET /api/audit?status=APPROVED` shows `decision_by/at/notes` + `incident_summary`.

7. **Dashboard** `GET /api/dashboard/reliability-trend?days=30` wavy SVG + `top-issues?limit=5` + `business-impact` + `GET /api/datasets` health cards → control centre answers *Is healthy? What broke? What’s at risk?*

**Frontend manual:** `http://localhost:3000` → Upload `orders_v1.csv` → See `HEALTHY` → Upload `orders_v2_schema_drift.csv` with baseline selector → Scan detail shows **WHAT** (gate) → **WHAT changed** → **AFFECTED** → **WHY/IMPACT/ACTION** → Approve → `/audit` shows trail. Real Olist `geolocation 58MB` now passes 100MB limit.

**Automated:** `cd apps/api && pytest tests/ -v` (17 tests) + `cd apps/web && npm run build` (6 routes) + `GET /api/lineage/config` editable via `PUT` in Datasets → Lineage tab.
