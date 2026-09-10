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

3. **Storage (`database/`)**:
   - PostgreSQL: Stores datasets, schemas, schema_columns, scans, issues, ai_analysis, remediations, dependencies.

4. **Integration & Demo Assets**:
   - Sample D2C datasets: baseline vs intentional schema drift & dirty data.
   - Complete Docker Compose for local orchestration.
