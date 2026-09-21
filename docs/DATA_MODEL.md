# DataGuard Data Model

## Relational Schema (PostgreSQL)

### `datasets`
- `id`: UUID / Integer (Primary Key)
- `name`: VARCHAR(255)
- `filename`: VARCHAR(255)
- `file_type`: VARCHAR(50) (e.g., 'csv', 'json')
- `row_count`: INTEGER
- `column_count`: INTEGER
- `created_at`: TIMESTAMP WITH TIME ZONE

### `schemas`
- `id`: UUID / Integer (Primary Key)
- `dataset_id`: FK -> `datasets.id`
- `fingerprint`: VARCHAR(64) (SHA256 hash of canonical column signatures)
- `created_at`: TIMESTAMP WITH TIME ZONE

### `schema_columns` (Watchtower-adapted)
- `id`: UUID / Integer (Primary Key)
- `schema_id`: FK -> `schemas.id`
- `column_name`: VARCHAR(255)
- `data_type`: VARCHAR(50) (INTEGER, FLOAT, STRING, DATE, BOOLEAN)
- `nullable`: BOOLEAN
- `unique_count`: INTEGER
- `null_count`: INTEGER
- `sample_values`: JSONB
- `null_rate`: FLOAT (0.0-1.0)
- `unique_ratio`: FLOAT
- `min_value`/`max_value`/`mean`/`median`/`p05`/`p95`: FLOAT (numeric only, IQR)
- `outlier_count`: INTEGER, `outlier_rate`: FLOAT
- `top_values`: JSONB `[{value,count,rate}]`

### `scans` (with incident + gate + quality score + incidents)
- `id`: UUID / Integer (Primary Key)
- `dataset_id`: FK -> `datasets.id`
- `baseline_dataset_id`: FK -> `datasets.id` nullable (explicit baseline via `baselines` table, fallback to prefix `like`; never silent)
- `status`: VARCHAR(50) ('RUNNING', 'COMPLETED', 'FAILED')
- `healthy_count`: INTEGER
- `warning_count`: INTEGER
- `critical_count`: INTEGER
- `incident_summary`: TEXT (Watchtower `_incident_report` human-friendly)
- `incident_severity`: VARCHAR(20) (INFO/WARNING/CRITICAL/PASSED)
- `quality_score`: FLOAT nullable (0-100 deterministic weighted sum, default 100.0)
- `quality_dimensions`: JSONB (`{completeness:{score,weight,critical,warning,evidence,issues}, ... freshness}` with weights `0.20/0.20/0.20/0.10/0.15/0.10/0.05`)
- `started_at`/`completed_at`: TIMESTAMP
- `incidents`: relationship `Incident` (one per scan, deterministic grouping)

### `incidents` (correlated, deterministic — Phase 7)
- `id`: UUID / Integer (Primary Key)
- `scan_id`: FK -> `scans.id` indexed
- `dataset_id`: FK -> `datasets.id` indexed
- `dataset_name`: VARCHAR(255) indexed (logical)
- `title`: VARCHAR(255) (deterministic from `incident_summary` + families)
- `severity`: VARCHAR(20) indexed (INFO/WARNING/CRITICAL)
- `status`: VARCHAR(20) indexed (OPEN, INVESTIGATING, RESOLVED, CLOSED)
- `root_cause`: TEXT (deterministic hypothesis: schema change, drift, quality breach, contract violation, upstream hint)
- `affected_columns`: JSONB (union of issue `column_name`)
- `affected_assets`: JSONB (downstream via `lineage.py` for affected columns)
- `issue_ids`: JSONB (list of `Issue` ids in incident)
- `issue_types`: JSONB (distinct `issue_type` list)
- `issue_count`: INTEGER
- `correlation_evidence`: JSONB (`{families, family_counts, overlapping_columns, downstream_assets, issue_count, scan_incident_summary, scan_quality_score}`)
- `quality_score_at_incident`: FLOAT
- `created_at`/`updated_at`: TIMESTAMP, `resolved_at`/`resolved_by`: nullable
- `incidents.py`: `FAMILY_MAP` (schema/drift/statistical/quality/contract → family), `correlate_incidents_for_scan` (one per scan, deterministic), never LLM

### `issues` (populated by `quality/` registry + `drift.py` + `statistical_drift.py` + `quality_contracts.py`)
- `id`: UUID / Integer (Primary Key)
- `scan_id`: FK -> `scans.id`
- `issue_type`: VARCHAR(100) (COLUMN_REMOVED, COLUMN_ADDED, TYPE_CHANGED, NULLABILITY_CHANGED, NULL_RATE_DRIFT, CARDINALITY_DRIFT, NUMERIC_DRIFT, ROW_COUNT_DRIFT, COLUMN_RENAMED_CANDIDATE, NUMERIC_PSI_DRIFT, NUMERIC_KS_DRIFT, CATEGORICAL_PSI_DRIFT, CATEGORICAL_JSD_DRIFT, EMPTY_DATASET, PRIMARY_KEY_NULL, DUPLICATE_PRIMARY_KEY, DUPLICATE_ROWS, HIGH_NULL_RATE, NEGATIVE_VALUE_ANOMALY, NUMERIC_ANOMALY, MALFORMED_DATE, CATEGORICAL_INCONSISTENCY, RULE_EXECUTION_ERROR, CONTRACT_BREACH_COMPLETENESS, CONTRACT_BREACH_UNIQUENESS, CONTRACT_BREACH_RANGE, CONTRACT_BREACH_REGEX, CONTRACT_BREACH_ROW_COUNT, CONTRACT_UNKNOWN_TYPE, CONTRACT_EVALUATION_ERROR)
- `severity`: VARCHAR(20) ('CRITICAL', 'WARNING', 'INFO')
- `column_name`: VARCHAR(255) (Nullable — for rename candidate `from -> to`)
- `description`: TEXT
- `metadata`: JSONB (per-rule/contract/drift/statistical evidence: `null_count`, `negative_count`, `invalid_count`, `inconsistent_variants`, `expected_*`/`actual_*`, `contract_id`, `version`, `from_column/to_column/confidence/evidence{name_similarity,type_compatibility,stat_similarity}`, `metric/psi/ks/jsd/threshold/evidence{baseline_percents,current_percents}`, etc.)
- `quality/` mapping: each `QualityRule` emits `RuleResult` → `to_issue_dict()` → `Issue` row; registry order mirrors legacy `quality.py` for stable snapshots; `contracts.py` supplies `primary_key` to `PrimaryKeyRule`; `quality_contracts.py` appends `CONTRACT_BREACH_*` issues during scan; `drift.py` appends `COLUMN_RENAMED_CANDIDATE` with evidence (never auto-asserts rename); `statistical_drift.py` appends `*PSI/*KS/*JSD_DRIFT` with `metric,threshold,evidence` when raw DataFrames available (sample-size guarded ≥30 rows, ≥5 uniques, ≤50 cats).

### `quality_contracts` (SodaCL / GE suite — Phase 2)
- `id`: UUID / Integer (Primary Key)
- `dataset_name`: VARCHAR(255) indexed (logical, e.g., `orders` matches `orders_v1` via prefix `orders_`)
- `column_name`: VARCHAR(255) nullable indexed (None for `row_count` table-level)
- `contract_type`: VARCHAR(50) indexed (`completeness`/`not_null`→completeness, `uniqueness`/`unique`→uniqueness, `range`, `regex`, `row_count`)
- `threshold`: FLOAT nullable (0.0-1.0 validity ratio; e.g., `0.99` for ≥99%, `1.0` for strict)
- `params`: JSONB (`{min,max}` for range/row_count, `{pattern}` for regex, extra)
- `severity`: VARCHAR(20) (CRITICAL/WARNING/INFO)
- `description`: TEXT (e.g., `customer_id must not be null ≥99%`)
- `enabled`: BOOLEAN (default true — disabled contracts skipped in scan, testable)
- `version`: INTEGER (incremented on `PUT`, `updated_at` tracks recency — versioned, explainable, separate from `issues`)
- `created_at`/`updated_at`: TIMESTAMP WITH TIME ZONE
- `quality_contracts.py`: `_contract_matches()` prefix logic, `evaluate_contracts()` deterministic pandas (completeness via null_rate, uniqueness via unique_ratio, range via validity ratio, regex via re, row_count via dataset.row_count), `create/update/delete` CRUD.

### `baselines` (explicit, versioned, never silent — Phase 6)
- `id`: UUID / Integer (Primary Key)
- `dataset_name`: VARCHAR(255) indexed (logical, e.g., `orders` → `orders_v1/v2`)
- `baseline_dataset_id`: FK -> `datasets.id` (physical dataset that is baseline)
- `baseline_schema_id`: FK -> `schemas.id` (schema for fingerprint)
- `fingerprint`: VARCHAR(64) (SHA256)
- `row_count`/`column_count`: INTEGER snapshot
- `quality_score`: FLOAT nullable (snapshot from latest scan at creation)
- `version`: INTEGER (increments per logical dataset)
- `is_active`: BOOLEAN indexed (only one active per logical, enforced via deactivation)
- `description`: TEXT, `created_by`: VARCHAR(255), `created_at`/`updated_at`: TIMESTAMP
- `baselines.py`: `_logical_name` prefix, `get_active_baseline`, `create_baseline` (deactivates previous), `list/activate/compare`; never silently updated after scan

### `ai_analysis` (history-aware, provider-agnostic)
- `id`: UUID / Integer (Primary Key)
- `scan_id`: FK -> `scans.id`
- `severity`: VARCHAR(20)
- `summary`: TEXT
- `root_cause`: TEXT (appends `Historical context: N prior healthy` when applicable)
- `impact`: TEXT (legacy ` -> ` join)
- `technical_impact`: TEXT
- `business_impact`: TEXT (e.g., Revenue reporting at risk)
- `affected_assets`: JSONB
- `recommended_action`: TEXT
- `confidence`: FLOAT (0.85/0.92/0.97 calibrated)
- `requires_human_approval`: BOOLEAN
- `created_at`: TIMESTAMP

### `dataset_contracts.json` (new, not a table)
- `customers: {table_type: entity, primary_key: [customer_id]}`
- `order_items: {table_type: fact, primary_key: [order_id, product_id]}` composite — prevents false `DUPLICATE_PRIMARY_KEY` on FKs
- `events: {table_type: event, primary_key: [event_id]}` — `user_id` correctly repeats
- Loaded via `contracts.py:get_contract(dataset_name)` with prefix fallback (`orders_v1` → `orders`)

### `remediations`
- `id`: UUID / Integer (Primary Key)
- `issue_id`: FK -> `issues.id` (Nullable)
- `scan_id`: FK -> `scans.id`
- `suggestion`: TEXT
- `status`: VARCHAR(50) ('PENDING', 'APPROVED', 'REJECTED')
- `decision_by`: VARCHAR(255)
- `decision_at`: TIMESTAMP WITH TIME ZONE
- `notes`: TEXT

### `dependencies` (Lineage — demo, legacy)
- `id`: UUID / Integer (Primary Key)
- `source_asset`: VARCHAR(255) (e.g. `orders.order_value`)
- `target_asset`: VARCHAR(255) (e.g. `revenue_model`)
- `relationship_type`: VARCHAR(50) (e.g. `DERIVED_BY`, `USED_BY_DASHBOARD`)
- File `lineage_config.json` editable via `GET/PUT /api/lineage/config` (`is_demo:true`) — now seeded into `lineage_edges` on first DB query

### `lineage_edges` (DB graph — Phase 8, OpenLineage/Marquez)
- `id`: UUID / Integer (Primary Key)
- `source_dataset`: VARCHAR(255) indexed (e.g., `orders`)
- `source_column`: VARCHAR(255) nullable indexed (e.g., `order_value`, None for dataset-level)
- `target_dataset`: VARCHAR(255) indexed (e.g., `revenue_model`)
- `target_column`: VARCHAR(255) nullable indexed
- `target_type`: VARCHAR(50) indexed (`DATASET`, `JOB`, `SQL_MODEL`, `DASHBOARD`)
- `job_name`: VARCHAR(255) nullable indexed (e.g., `revenue_pipeline`)
- `run_id`: VARCHAR(100) nullable indexed (e.g., `run_123`)
- `relationship`: VARCHAR(50) (`DIRECT`, `TRANSFORMED`, `AGGREGATION`, etc.)
- `description`: TEXT, `is_active`: BOOLEAN indexed, `created_by`: VARCHAR(255), `created_at`/`updated_at`: TIMESTAMP
- `lineage_graph.py`: `_ensure_seeded` from `lineage_config.json`, `create_edge`, `list_edges`, `get_direct_downstream/upstream`, `traverse_graph` BFS with `max_depth` 1-5 and cycle protection via `visited`, `get_lineage_graph` both directions; APIs `POST/GET/DELETE /api/lineage/edges`, `GET /api/lineage/graph`, `GET /api/lineage/{dataset}/downstream/upstream`, enhanced `GET /api/lineage/{dataset}/{column}` (DB first, `is_demo` flag for seeded vs custom)

### `schemas` + `schema_columns` + historical evolution (Phase 4) + statistical (Phase 5) + baselines (Phase 6) + reliability (Phase 10) + anomaly (Phase 11)
- `schemas` stores per-physical-dataset fingerprint + `created_at`; `schema_columns` stores profiling stats (null_rate, unique_ratio, mean, etc.)
- Historical versions: per-physical `GET /api/datasets/{id}/schemas` + per-logical `GET /api/datasets/{id}/schema/history` (physical + logical `orders%` evolution)
- Schema compare `GET /api/datasets/{id}/schema/compare?baseline_dataset_id=` returns `drift_issues` including `COLUMN_RENAMED_CANDIDATE` with `confidence/evidence` (name_sim, type_compat, stat_sim) + `statistical_drifts` (`NUMERIC_PSI/KS`, `CATEGORICAL_PSI/JSD` via `statistical_drift.py` quantile bins / ECDF / JSD, thresholds PSI 0.1/0.25, KS 0.2/0.4, JSD 0.1/0.2, sample-size guarded)
- Statistical drift integrated into `detect_schema_drift(..., baseline_df, current_df)` when raw DataFrames available (scan preloads via storage); otherwise falls back to Watchtower mean/outlier drift without false precision
- Baselines `baselines` table: `id`, `dataset_name` logical, `baseline_dataset_id` FK, `baseline_schema_id` FK, `fingerprint`, `row_count/column_count`, `quality_score` snapshot, `version`, `is_active` (only one active per logical), `description`, `created_by`, `created_at/updated_at`; APIs `POST/GET /api/baselines`, `GET/PUT/DELETE /api/baselines/{id}`, `PUT .../activate`, `GET /api/datasets/{id}/baselines`, `GET /api/baselines/{id}/compare/{dataset_id}`; scan uses active baseline when no explicit `baseline_dataset_id` (never silent, fallback to prefix search)
- Reliability `reliability.py` (computed, no new tables): per-day `scans/avg_quality_score/critical/warning/healthy/incidents`, `most_problematic_datasets` (lowest avg_score/highest incidents), `most_problematic_columns` (issue frequency), `incident_frequency`, `quality_degradation` (recent 5 vs historical 5 delta threshold `-5`); APIs `GET /api/reliability/*`
- Anomaly `anomaly.py` (computed, no ML): ` _is_anomalous_zscore` (`|z|≥2 warning/≥3 critical`, IQR fallback `q1-1.5*IQR`), `detect_null_rate_anomalies` via `schema_columns.null_rate` history, `detect_quality_score_anomaly` via `Scan.quality_score`, `detect_row_count_anomaly`, `detect_anomalies_for_scan/dataset` union; each anomaly with `anomaly_type/severity/column/dataset/current/historical_mean/std/z_score/evidence{method, historical_range, threshold}`; APIs `GET /api/anomalies`, `GET /api/datasets/{id}/anomalies`, `GET /api/scans/{id}/anomalies`

### `storage` + migrations
- `storage_backend.py`: `local` `storage/{id}_{filename}` → `s3://` if `STORAGE_BACKEND=s3` (boto3 optional)
- `database.py:run_migrations()` additive `ALTER TABLE` on startup (covers `scans.baseline_dataset_id/incident_*/quality_score/quality_dimensions` + `schema_columns.*` + `ai_analysis.*`), 100MB upload limit (handles Olist 58MB)
