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
- **AI Agent**: OpenAI GPT-4o with structured Pydantic outputs & deterministic offline fallback
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

All 7 core test suites execute without requiring network access or third-party API keys.

---

## 🎬 Repeatable Demo Walkthrough

1. **Upload Baseline (`sample-data/orders_v1.csv`)**:
   - Ingests cleanly.
   - Status: 🟢 **HEALTHY** (0 critical issues).
2. **Upload Drifted Dataset (`sample-data/orders_v2_schema_drift.csv`)**:
   - Deterministic engine flags:
     - ❌ `order_value` column removed.
     - ⚠️ `order_amount` column added.
     - ❌ `discount` datatype drifted: `FLOAT` → `STRING`.
   - Status: 🔴 **CRITICAL**.
3. **AI Analyst Reasoning**:
   - Evaluates scan findings and identifies probable root cause: upstream field rename from `order_value` to `order_amount`.
4. **Downstream Lineage Impact**:
   - Traces impact to `revenue_model`, `monthly_revenue`, and `Executive Revenue Dashboard`.
5. **Human Approval**:
   - The operator clicks **[Approve Remediation]** to record the migration decision in the audit log.
