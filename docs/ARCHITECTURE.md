# DataGuard Architecture

## Architectural Philosophy: Strict Engine-AI Separation

```
                    DATA (CSV / JSON)
                            │
                            ▼
               DETERMINISTIC ENGINE (Python)
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
        Schema Rules   Quality Rules   Impact Rules
        (Drift, Types) (Nulls, Dupes)  (Lineage DAG)
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                    SCAN RESULTS / ISSUES
                            │
                            ▼
                   OPENAI ANALYST AGENT
                   (Reasons over Issues)
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
          Explain       Root Cause     Remediation
                            │
                            ▼
                     HUMAN APPROVAL
                (Approve / Reject Action)
```

## System Components

1. **Frontend (`apps/web`)**:
   - Next.js (App Router) + TypeScript + Tailwind CSS.
   - Dashboard: Pipeline Health overview, Recent Scans, Upload interface.
   - Dataset & Scan Views: Detailed Schema Diff, Quality findings, Downstream Impact Graph, AI Recommendation card with [Approve] / [Reject] actions.

2. **Backend (`apps/api`)**:
   - FastAPI (Python 3.11+).
   - `scanner.py`: Ingestion, validation, profiling.
   - `schema.py`: Schema fingerprinting and drift comparison.
   - `quality.py`: Deterministic data quality rules (nulls, ranges, duplicates, formats).
   - `lineage.py`: Dependency graph mapping (Column -> SQL Model -> Dashboard).
   - `ai.py`: OpenAI Analyst Agent returning structured Pydantic outputs.
   - Database layer: SQLAlchemy / asyncpg ORM mapping to PostgreSQL.

3. **Storage (`database/` + `storage_backend.py`)**:
    - PostgreSQL with `run_migrations()` additive `ALTER TABLE` on startup (no Alembic, safe for SQLite/PG): `scans.baseline_dataset_id/incident_*`, `schema_columns.null_rate/.../top_values`, `ai_analysis.technical_impact/business_impact`.
    - `storage_backend.py` abstraction: `local` `storage/{id}_{filename}` → `s3://` if `STORAGE_BACKEND=s3` + `S3_BUCKET` (boto3 optional fallback). Upload limit 100MB (handles Olist geolocation 58MB).

4. **AI (`ai.py` + `ai_provider.py`)**:
    - Provider-agnostic `AIProvider` (mock/openai/gemini via `AI_PROVIDER`), structured `AIAnalysisOutput` with `technical_impact/business_impact`, history-aware fallback (last 3 scans per `orders` prefix → `Historical context: 2 prior healthy`).

5. **Product Surfaces**:
    - Dashboard: HealthCards + ReliabilityTrend (30d wavy SVG) + TopIssues (5) + BusinessImpact (Revenue/Customer/Margin) + Recent Scans with Business Impact column + Ingest (100MB) + Demo seeds.
    - Datasets: `/datasets` health cards + `/datasets/[id]` 5 tabs (Overview with baseline `<select>`+Scan trigger, Schema with `null_rate/mean/top_values`, Quality, History sparkline + `business_impact`, Lineage editable `lineage_config.json` via `PUT /api/lineage/config`).
    - Scans: `scans/[id]` ordered WHAT (incident+gate `PASS/FAIL`) → WHAT changed → AFFECTED (ImpactGraph `is_demo:true`) → WHY/IMPACT/ACTION (AI) → Audit Timeline → Approve/Reject → `/audit?status=&severity=&dataset_id=` filters.

6. **Integration & Demo Assets**:
    - Real Olist 9 CSVs (99k orders, 1M geolocation) verified live: `olist_geolocation_dataset.csv` 58MB now passes.
    - `GET /api/datasets/{id}/history` includes `business_impact`, `GET /dashboard/*` 3 endpoints, `GET /scans/{id}/gate`, `POST /scans/{id}/analyze` history-aware.
    - Tests: 17 hermetic `pytest` (7 core + 10 Watchtower: IQR, drift thresholds, gate, history, lineage config) + `next build` 6 routes.
