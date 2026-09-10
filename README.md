# DataGuard 🛡️
> **AI-Powered Data Reliability & Schema Drift Platform**

DataGuard is an end-to-end data reliability platform that detects schema drift and data-quality degradation before corrupted records contaminate downstream analytics, SQL models, and executive dashboards.

---

## 🏗️ Core Architectural Principle: Strict Engine-AI Separation

```
                    DATA (CSV / JSON)
                            │
                            ▼
               DETERMINISTIC ENGINE (Python)
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
        Schema Drift   Data Quality   Lineage DAG
        (Types, Nulls) (Bounds, Outliers) (Asset Graph)
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                    Deterministic Findings
                            │
                            ▼
                   OPENAI ANALYST AGENT
               (Reasons over Scan Findings)
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
          Explain       Root Cause    Remediation
                            │
                            ▼
                     HUMAN APPROVAL
                (Audit Logged Decision)
```

> **The Golden Rule**: The deterministic engine calculates facts (null rates, type changes, missing columns). The LLM is strictly used for reasoning, downstream impact tracing, and proposing human-reviewable remediations. The AI never modifies production data automatically.

---

## ⚡ Tech Stack

- **Frontend**: Next.js (App Router), TypeScript, Tailwind CSS, Lucide Icons
- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0, Pandas, NumPy
- **Database**: PostgreSQL (with SQLite fallback for local unit tests)
- **AI Agent**: Provider-agnostic (OpenAI / Gemini / Mock fallback) with structured Pydantic outputs — `AI_PROVIDER=mock|openai|gemini`
- **Orchestration**: Docker Compose

---

## 🚀 Quickstart Guide

### Option 1: Running with Docker Compose (Full Stack)

```bash
# Clone and enter directory
cd dataguard

# Start PostgreSQL, FastAPI Backend, and Next.js Web
docker compose up --build
```

- **Web Dashboard**: [http://localhost:3000](http://localhost:3000)
- **FastAPI Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

### Option 2: Running Locally

#### 1. Start Backend
```bash
cd dataguard/apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run server (defaults to local SQLite if DATABASE_URL is not set)
uvicorn main:app --reload --port 8000
```

#### 2. Start Frontend
```bash
cd dataguard/apps/web
npm install
npm run dev
```

Visit [http://localhost:3000](http://localhost:3000).

---

## 🧪 Running Tests

DataGuard features 100% hermetic unit and integration tests:

```bash
cd dataguard/apps/api
source .venv/bin/activate
PYTHONPATH=. pytest tests/ -v
```

17 tests (7 core + 10 Watchtower-adapted incl. lineage/config, history business impact) execute hermetically without network or API keys. Frontend `next build` 6 routes.

---

## 🎬 Repeatable Demo Walkthrough (60-sec)

1. **Baseline `orders_v1.csv`** → 🟢 **HEALTHY** — `incident_summary: Healthy profile change` • no business impact.
2. **Schema drift `orders_v2_schema_drift.csv`** → 🔴 **CRITICAL** — `order_value` removed, `order_amount` added, `discount FLOAT→STRING`, null-rate + row-count drift. Gate `FAIL`.
3. **Quality bugs `orders_bad_quality.csv`** → 🔴 **CRITICAL** — `NEGATIVE_VALUE_ANOMALY`, `DUPLICATE_PRIMARY_KEY`, `MALFORMED_DATE`, numeric distribution shift (`order_value` mean 842→4480).
4. **What it means** — deterministic `incident_summary` + business impact: *“Revenue reporting at risk: Executive Dashboard will be understated”* with lineage `orders.order_value → revenue_model → Executive Revenue Dashboard` (demo lineage flag).
5. **AI Analyst** — explains rename hypothesis, technical + business impact separately, recommends mapping. Provider-agnostic (`mock` by default, `gemini`/`openai` if key set).
6. **Human Approval** → `[Approve]` records `decision_by/at/notes` → visible in `/audit` trail.

**Control Center:** Overview shows *Reliability Trend* (wavy 30d), *Top Active Issues* (5), *Business Impact* (Revenue/Customer/Margin at risk), Datasets with health/history/l lineage editor (`PUT /api/lineage/config`), and Scan detail ordered WHAT (gate+incident) → WHAT changed → AFFECTED → IMPACT → ACTION → Audit Timeline. Upload limit 100MB (handles Olist geolocation 58MB); audit at `/audit` supports `?status=&severity=&dataset_id=` filters. Recent Scans now shows **Business Impact** column.

**Real data tested:** Olist 9 CSVs (olist_orders 99k rows, geolocation 1M rows) — all profiled via Watchtower IQR + quality checks; `olist_geolocation_dataset.csv` (58MB) now passes 100MB limit after P5 fix.
