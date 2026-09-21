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
   - `scanner.py`: Ingestion, validation, profiling (Pandas + IQR outlier detection).
   - `drift.py` + `statistical_drift.py`: Schema evolution & statistical drift — **Phase 4-5** (Watchtower + rename + PSI/KS/JSD):
     - Detects `COLUMN_REMOVED`/`COLUMN_ADDED`/`TYPE_CHANGED`/`NULLABILITY_CHANGED` + Watchtower `NULL_RATE/CARDINALITY/NUMERIC/ROW_COUNT` drifts, row-count gate.
     - Rename detection: evidence-based `COLUMN_RENAMED_CANDIDATE` (never auto-claims) with confidence `0.5*name_sim +0.3*type_compat +0.2*stat_sim` via `difflib.SequenceMatcher + token overlap` + type compatibility + null_rate/unique_ratio delta; thresholds `possible ≥0.60`, `likely ≥0.75`, `very likely ≥0.85`, emitted as `INFO` with `from_column/to_column/confidence/evidence` (name_sim, type_compat, stat_sim), greedy one-to-one.
     - Statistical drift: `statistical_drift.py` with PSI (categorical via category frequencies, numeric via 10 quantile bins), KS (numeric ECDF max diff), JSD (categorical distribution) — deterministic numpy/pandas, sample-size guarded (≥30 rows, ≥5 uniques), thresholds PSI `0.1 warning/0.25 critical`, KS `0.2/0.4`, JSD `0.1/0.2`, each finding contains `metric, baseline/current, threshold, severity, evidence, affected column`.
     - Chooses method per type: numeric → PSI+KS (≥30 rows), categorical → PSI+JSD (≤50 cats), avoids false precision on small samples; integrated via `detect_schema_drift(..., baseline_df, current_df)` when raw DataFrames available (scan preloads via storage, compare endpoint loads both).
     - Historical schema versions: per-physical `Schemas` + logical evolution across `orders%` prefix; endpoints `GET /api/datasets/{id}/schemas`, `GET /api/datasets/{id}/schema/history` (physical + logical), `GET /api/datasets/{id}/schema/compare?baseline_dataset_id=` (drift + rename + statistical).
     - Incident summary + gate unchanged; scoring maps `NUMERIC_PSI/KS`, `CATEGORICAL_PSI/JSD` → `distribution_stability` (INFO/WARNING/CRITICAL).
   - `quality/`: Modular deterministic quality engine — **Phase 1** (Great Expectations / Soda-inspired):
     - `quality/rule.py` (`QualityRule` ABC) + `quality/result.py` (`RuleResult`) + `quality/registry.py` (`QualityRuleRegistry`) + `quality/engine.py` (`QualityEngine` + `run_quality_checks()` façade).
     - `quality/rules/` — 8 isolated rules: `empty_dataset`, `primary_key` (contract-aware composite), `duplicate_rows`, `null_rate`, `negative_value`, `numeric_anomaly` (z-score), `date_validation`, `categorical_consistency`.
     - Preserves original `from quality import run_quality_checks` signature for zero-breakage; registry is insertion-ordered, each rule is deterministic, explainable, and unit-testable.
     - Pattern study: Great Expectations Expectations → typed per-check class + Validator; Soda Core declarative checks → registry/scan executor. DataGuard reimplements natively (no external dep).
   - `quality_contracts.py` + `QualityContract` table — **Phase 2** (SodaCL / GE suite declarative contracts):
     - Declarative expectations: `completeness` (e.g., `customer_id ≥99%`), `uniqueness` (`order_id =100%`), `range` (`amount positive ≥99.5%` via `min/max + threshold`), `regex` (pattern + threshold), `row_count` (table-level min/max).
     - Stored in `quality_contracts` (versioned `version` int + `updated_at`, `enabled` flag, `params` JSON), validated via Pydantic (`threshold 0-1`, `severity` enum), separate from `issues` scan results.
     - Dataset matching uses prefix logic (`orders` matches `orders_v1`/`orders_bad_quality`) mirroring `contracts.py`; evaluation is deterministic pandas with evidence (`expected vs actual`, `null_count`, `invalid_samples`, `version`).
     - API: `POST/GET/PUT/DELETE /api/contracts`, `GET /api/datasets/{id}/contracts`, `POST /api/datasets/{id}/contracts/evaluate`; integrated into `scan_dataset:322` — contracts evaluated against `df_quality` and appended to `all_issues` as `CONTRACT_BREACH_*` (explainable, testable).
   - `lineage.py`: Dependency graph mapping (Column -> SQL Model -> Dashboard).
   - `quality_score.py` — **Phase 3** (OpenMetadata/Elementary dimensions):
     - 7 dimensions `completeness, uniqueness, validity, consistency, schema_stability, distribution_stability, freshness` weighted `0.20/0.20/0.20/0.10/0.15/0.10/0.05` → weighted sum 0-100, integer, clamped.
     - Penalty deterministic: `CRITICAL -25`, `WARNING -10` per issue in dimension, plus freshness from `max date` recency (`≤7d 100, ≤30d 95, ≤90d 80, >90d 60`).
     - Mapping `issue_type→dimension` (single assignment to avoid double penalty), explainable `evidence` per dimension, overall `summary` with weakest dimension hint.
     - Persisted on `scans.quality_score`/`quality_dimensions` (JSON) via `compute_quality_score()` during scan; endpoint `GET /api/scans/{id}/score` recomputes for legacy scans; history includes `quality_score`.
     - Study: OpenMetadata data quality dimensions + Elementary reliability trends → unified score.
   - `baselines.py` + `Baseline` table — **Phase 6** (Marquez/OpenLineage baseline concept):
     - Explicit, versioned (`version` increments per logical `dataset_name`), never silent; `dataset_name` logical (e.g., `orders` → `orders_v1/v2`), `baseline_dataset_id/schema_id`, `fingerprint/row_count/column_count/quality_score` snapshot, `is_active` (only one active per logical), `created_by/description`, `created_at`.
     - Manager `baselines.py` with `_logical_name` prefix logic, `get_active_baseline`, `create_baseline` (deactivates previous active), `list/activate/compare`; scan uses active baseline when no explicit `baseline_dataset_id` (fallback to prefix search).
     - APIs: `POST/GET /api/baselines`, `GET/PUT/DELETE /api/baselines/{id}`, `PUT .../activate`, `GET /api/datasets/{id}/baselines`, `GET /api/baselines/{id}/compare/{dataset_id}`.
   - `contracts.py` + `dataset_contracts.json`: Table-type & PK contracts (entity/fact/event) eliminating heuristic `endswith _id` false positives.
   - `ai.py` + `ai_provider.py`: OpenAI/Gemini/Mock analyst with structured `AIAnalysisOutput`.
   - Database layer: SQLAlchemy 2.0 → PostgreSQL (SQLite fallback for hermetic tests); `quality_contracts` + `baselines` + `scans.quality_score/dimensions` via `create_all` + `run_migrations()` additive `ALTER TABLE`.

3. **Storage (`database/` + `storage_backend.py`)**:
    - PostgreSQL with `run_migrations()` additive `ALTER TABLE` on startup (no Alembic, safe for SQLite/PG): `scans.baseline_dataset_id/incident_*/quality_score/quality_dimensions`, `schema_columns.null_rate/.../top_values`, `ai_analysis.technical_impact/business_impact`.
    - `storage_backend.py` abstraction: `local` `storage/{id}_{filename}` → `s3://` if `STORAGE_BACKEND=s3` + `S3_BUCKET` (boto3 optional fallback). Upload limit 100MB (handles Olist geolocation 58MB).

4. **AI (`ai.py` + `ai_provider.py`)**:
    - Provider-agnostic `AIProvider` (mock/openai/gemini via `AI_PROVIDER`), structured `AIAnalysisOutput` with `technical_impact/business_impact`, history-aware fallback (last 3 scans per `orders` prefix → `Historical context: 2 prior healthy`).

5. **Product Surfaces**:
    - Dashboard: HealthCards + ReliabilityTrend (30d wavy SVG) + TopIssues (5) + BusinessImpact (Revenue/Customer/Margin) + Recent Scans with Business Impact column + Ingest (100MB) + Demo seeds.
    - Datasets: `/datasets` health cards + `/datasets/[id]` 5 tabs (Overview with baseline `<select>`+Scan trigger, Schema with `null_rate/mean/top_values`, Quality, History sparkline + `business_impact`, Lineage editable `lineage_config.json` via `PUT /api/lineage/config`).
    - Scans: `scans/[id]` ordered WHAT (incident+gate `PASS/FAIL`) → WHAT changed → AFFECTED (ImpactGraph `is_demo:true`) → WHY/IMPACT/ACTION (AI) → Audit Timeline → Approve/Reject → `/audit?status=&severity=&dataset_id=` filters.

6. **Integration & Demo Assets**:
    - Real Olist 9 CSVs (99k orders, 1M geolocation) verified live: `olist_geolocation_dataset.csv` 58MB now passes; `orders_v1 → orders_v2` rename `order_value→order_amount` produces `COLUMN_RENAMED_CANDIDATE`; `amount` distribution shift 100→500 triggers `NUMERIC_PSI_DRIFT` + `CATEGORICAL_PSI_DRIFT`.
    - `GET /api/datasets/{id}/history` now includes `quality_score`/`quality_dimensions` + `business_impact`, `GET /dashboard/*` 3 endpoints, `GET /scans/{id}/gate`, `GET /scans/{id}/score` (dimensions + summary), `GET /api/datasets/{id}/schema/history` + `.../schema/compare` (now with statistical drifts), `GET /api/baselines` + `.../baselines/{id}/compare/{dataset_id}` for explicit baseline lifecycle, `POST /scans/{id}/analyze` history-aware.
    - Contracts: `GET /api/contracts` + `POST /api/datasets/{id}/contracts/evaluate` for Soda-style declarative checks.
    - Tests: 66 hermetic `pytest` (7 core + 10 Watchtower + 13 contracts + 10 quality_score + 5 schema_evolution + 14 statistical_drift + 7 baselines) + `next build` 6 routes.
