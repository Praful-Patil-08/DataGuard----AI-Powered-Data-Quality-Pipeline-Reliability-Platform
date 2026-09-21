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
   - `incidents.py` + `Incident` table — **Phase 7** (Elementary incident layer):
     - Deterministic correlation: one incident per scan grouping all related issues via evidence (same scan, same dataset, column overlap, issue_type families `schema/drift/statistical/quality/contract`, downstream lineage overlap `orders.order_value → revenue_model`).
     - Never uses LLM; `FAMILY_MAP` single-assignment, `generate_incident_title`/`generate_root_cause` deterministic hypothesis (schema change, drift, quality breach, contract violation, upstream check hint), `correlation_evidence` with `families/family_counts/overlapping_columns/downstream_assets/issue_count`.
     - Persisted `incidents` (`scan_id/dataset_id/dataset_name/title/severity/status/root_cause/affected_columns/affected_assets/issue_ids/issue_types/issue_count/correlation_evidence/quality_score_at_incident`), status `OPEN→RESOLVED/CLOSED` via `PUT /api/incidents/{id}`.
     - APIs: `GET /api/incidents` (filter `dataset_id/name/severity/status`), `GET /api/incidents/{id}`, `PUT ...` (status), `GET /api/scans/{id}/incidents`, `GET /api/datasets/{id}/incidents`; scan auto-creates incident via `correlate_incidents_for_scan`.
     - Study: Elementary incident grouping + OpenLineage downstream impact → deterministic correlation.
   - `lineage.py` + `lineage_graph.py` + `LineageEdge` table — **Phase 8** (OpenLineage/Marquez graph):
     - Graph model: `LineageEdge` (`source_dataset/source_column → target_dataset/target_column` via `job_name/run_id`, `target_type` `DATASET/JOB/SQL_MODEL/DASHBOARD`, `relationship` `DIRECT/TRANSFORMED/AGGREGATION`, `is_active`, `created_by`) — OpenLineage `Dataset/Job/Run` + Marquez storage/API concepts, lightweight.
     - Seeded from `lineage_config.json` (demo) into DB on first query via `_ensure_seeded`, fallback to heuristic (`_joined_view`, `daily_metrics`) if no edge; DB-backed `is_demo` flag (seeded demo vs custom production).
     - Traversal: BFS `traverse_graph` with `max_depth` 1-5, cycle protection via `visited` set, dataset+column level, upstream/downstream, `get_lineage_graph` both directions; `get_direct_downstream/upstream` for 1-hop.
     - APIs: `POST/GET/DELETE /api/lineage/edges`, `GET /api/lineage/graph?dataset=&column=&depth=`, `GET /api/lineage/{dataset}/downstream?column=&depth=`, `GET /api/lineage/{dataset}/upstream`, enhanced `GET /api/lineage/{dataset}/{column}` (DB first, demo flag), `GET /api/lineage/config` file editable; incidents use `get_downstream_impact` DB for `affected_assets`.
     - Study: OpenLineage lineage events + Marquez graph storage → demonstrable lineage without distributed platform.
   - `impact.py` — **Phase 9** (Business Impact via lineage):
     - Deterministic propagation: `analyze_impact` (single column) + `analyze_scan_impact` (union per scan) using `lineage_graph.traverse_graph`, severity decay `CRITICAL@1→WARNING@2→INFO@3`, KPI aggregation `Revenue reporting/Customer segmentation/Margin analysis` via `KPI_MAP` heuristic, evidence `distance/relationship/evidence` per asset.
     - Answers what/datasets/pipelines/dashboards, how far (hops), which KPI, what severity — deterministic; AI explains afterward.
     - APIs: `GET /api/impact/{dataset}/{column}?severity=&depth=`, `GET /api/impact/{dataset}`, `GET /api/scans/{scan_id}/impact`, `GET /api/incidents/{incident_id}/impact`.
   - `reliability.py` — **Phase 10** (Elementary historical reliability):
     - Deterministic analytics over `Scan/Issue/Incident`: `get_reliability_trends` (per-day `scans/avg_quality_score/critical/warning/healthy/incidents`), `get_most_problematic_datasets` (avg_score ascending, incidents descending), `get_most_problematic_columns` (issue frequency, `critical_count` ranking), `get_incident_frequency` (per-day), `detect_quality_degradation` (recent 5 avg vs historical 5 avg, threshold `-5`, `trend_decreasing` check), `get_reliability_overview` (totals, avg_score, degradation, top 3 datasets/columns, 7d incidents).
     - No new tables — computed on-the-fly with windowed queries, deterministic, explainable (`evidence` with recent/historical avg, delta, threshold).
     - APIs: `GET /api/reliability/overview`, `GET /api/reliability/trends?dataset_id=&days=`, `GET /api/reliability/datasets?limit=&days=`, `GET /api/reliability/columns?limit=&days=`, `GET /api/reliability/incidents?days=&dataset_id=`, `GET /api/reliability/degradation?dataset_id=&window=`.
   - `anomaly.py` — **Phase 11** (Historical Anomaly Detection):
     - Statistical, no ML: `_is_anomalous_zscore` with z-score `|z|≥2 warning/≥3 critical` (n≥5, std>0) fallback IQR fence `q1-1.5*IQR`/`q3+1.5*IQR` (n<5 or std=0), `detect_null_rate_anomalies` (historical null_rate per column from `schema_columns`), `detect_quality_score_anomaly` (historical `quality_score` per logical), `detect_row_count_anomaly`, `detect_anomalies_for_scan` (union), `detect_anomalies_for_dataset` (latest vs history).
     - Each anomaly with `anomaly_type/severity/column/dataset/current/historical_mean/std/z_score/evidence{method, historical_range, threshold, delta}, description` — deterministic, explainable, e.g., null 2.1%→14.8% `z>3` critical.
     - APIs: `GET /api/anomalies?dataset_name=&window=`, `GET /api/datasets/{dataset_id}/anomalies?window=`, `GET /api/scans/{scan_id}/anomalies?window=`.
     - Study: Elementary anomaly patterns — statistical methods sufficient, no fake ML.
   - `contracts.py` + `dataset_contracts.json`: Table-type & PK contracts (entity/fact/event) eliminating heuristic `endswith _id` false positives.
   - `ai.py` + `ai_provider.py`: OpenAI/Gemini/Mock analyst with structured `AIAnalysisOutput`.
   - Database layer: SQLAlchemy 2.0 → PostgreSQL (SQLite fallback for hermetic tests); `quality_contracts` + `baselines` + `incidents` + `lineage_edges` + `scans.quality_score/dimensions` via `create_all` + `run_migrations()` additive `ALTER TABLE`.

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
    - `GET /api/datasets/{id}/history` now includes `quality_score`/`quality_dimensions` + `business_impact`, `GET /dashboard/*` 3 endpoints, `GET /scans/{id}/gate`, `GET /scans/{id}/score` (dimensions + summary), `GET /api/datasets/{id}/schema/history` + `.../schema/compare` (now with statistical drifts), `GET /api/baselines` + `.../baselines/{id}/compare/{dataset_id}` for explicit baselines, `GET /api/incidents` + `.../scans/{id}/incidents` for correlated incidents, `GET /api/lineage/graph` + `.../{dataset}/downstream/upstream` + `.../edges` for DB graph, `GET /api/impact/{dataset}/{column}` + `.../scans/{scan_id}/impact` for downstream business impact, `GET /api/reliability/overview` + `.../trends` + `.../datasets` + `.../columns` + `.../incidents` + `.../degradation` for historical reliability, `GET /api/anomalies` + `.../datasets/{id}/anomalies` + `.../scans/{id}/anomalies` for historical anomaly detection, `POST /scans/{id}/analyze` history-aware.
    - Contracts: `GET /api/contracts` + `POST /api/datasets/{id}/contracts/evaluate` for Soda-style declarative checks.
    - Tests: 108 hermetic `pytest` (7 core + 10 Watchtower + 13 contracts + 10 quality_score + 5 schema_evolution + 14 statistical_drift + 7 baselines + 8 incidents + 9 lineage_graph + 9 impact + 7 reliability + 9 anomaly) + `next build` 6 routes.
