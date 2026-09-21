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

### `scans` (with incident + gate + quality score)
- `id`: UUID / Integer (Primary Key)
- `dataset_id`: FK -> `datasets.id`
- `baseline_dataset_id`: FK -> `datasets.id` nullable (explicit baseline, replaces fuzzy `like`)
- `status`: VARCHAR(50) ('RUNNING', 'COMPLETED', 'FAILED')
- `healthy_count`: INTEGER
- `warning_count`: INTEGER
- `critical_count`: INTEGER
- `incident_summary`: TEXT (Watchtower `_incident_report` human-friendly)
- `incident_severity`: VARCHAR(20) (INFO/WARNING/CRITICAL/PASSED)
- `quality_score`: FLOAT nullable (0-100 deterministic weighted sum, default 100.0)
- `quality_dimensions`: JSONB (`{completeness:{score,weight,critical,warning,evidence,issues}, ... freshness}` with weights `0.20/0.20/0.20/0.10/0.15/0.10/0.05`)
- `started_at`/`completed_at`: TIMESTAMP

### `issues` (populated by `quality/` registry + `drift.py` + `quality_contracts.py`)
- `id`: UUID / Integer (Primary Key)
- `scan_id`: FK -> `scans.id`
- `issue_type`: VARCHAR(100) (COLUMN_REMOVED, COLUMN_ADDED, TYPE_CHANGED, NULLABILITY_CHANGED, NULL_RATE_DRIFT, CARDINALITY_DRIFT, NUMERIC_DRIFT, ROW_COUNT_DRIFT, COLUMN_RENAMED_CANDIDATE, EMPTY_DATASET, PRIMARY_KEY_NULL, DUPLICATE_PRIMARY_KEY, DUPLICATE_ROWS, HIGH_NULL_RATE, NEGATIVE_VALUE_ANOMALY, NUMERIC_ANOMALY, MALFORMED_DATE, CATEGORICAL_INCONSISTENCY, RULE_EXECUTION_ERROR, CONTRACT_BREACH_COMPLETENESS, CONTRACT_BREACH_UNIQUENESS, CONTRACT_BREACH_RANGE, CONTRACT_BREACH_REGEX, CONTRACT_BREACH_ROW_COUNT, CONTRACT_UNKNOWN_TYPE, CONTRACT_EVALUATION_ERROR)
- `severity`: VARCHAR(20) ('CRITICAL', 'WARNING', 'INFO')
- `column_name`: VARCHAR(255) (Nullable — for rename candidate `from -> to`)
- `description`: TEXT
- `metadata`: JSONB (per-rule/contract/drift evidence: `null_count`, `negative_count`, `invalid_count`, `inconsistent_variants`, `expected_*`/`actual_*`, `contract_id`, `version`, `from_column/to_column/confidence/evidence{name_similarity,type_compatibility,stat_similarity}`, etc.)
- `quality/` mapping: each `QualityRule` emits `RuleResult` → `to_issue_dict()` → `Issue` row; registry order mirrors legacy `quality.py` for stable snapshots; `contracts.py` supplies `primary_key` to `PrimaryKeyRule`; `quality_contracts.py` appends `CONTRACT_BREACH_*` issues during scan; `drift.py` appends `COLUMN_RENAMED_CANDIDATE` with evidence (never auto-asserts rename).

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

### `dependencies` (Lineage — demo)
- `id`: UUID / Integer (Primary Key)
- `source_asset`: VARCHAR(255) (e.g. `orders.order_value`)
- `target_asset`: VARCHAR(255) (e.g. `revenue_model`)
- `relationship_type`: VARCHAR(50) (e.g. `DERIVED_BY`, `USED_BY_DASHBOARD`)
- File `lineage_config.json` editable via `GET/PUT /api/lineage/config` (`is_demo:true`)

### `schemas` + `schema_columns` + historical evolution (Phase 4)
- `schemas` stores per-physical-dataset fingerprint + `created_at`; `schema_columns` stores profiling stats (null_rate, unique_ratio, mean, etc.)
- Historical versions: per-physical `GET /api/datasets/{id}/schemas` + per-logical `GET /api/datasets/{id}/schema/history` (physical + logical `orders%` evolution)
- Schema compare `GET /api/datasets/{id}/schema/compare?baseline_dataset_id=` returns `drift_issues` including `COLUMN_RENAMED_CANDIDATE` with `confidence/evidence` (name_sim, type_compat, stat_sim), INFO severity (never suppresses `COLUMN_REMOVED`/`COLUMN_ADDED` CRITICAL/WARNING)

### `storage` + migrations
- `storage_backend.py`: `local` `storage/{id}_{filename}` → `s3://` if `STORAGE_BACKEND=s3` (boto3 optional)
- `database.py:run_migrations()` additive `ALTER TABLE` on startup (covers `scans.baseline_dataset_id/incident_*/quality_score/quality_dimensions` + `schema_columns.*` + `ai_analysis.*`), 100MB upload limit (handles Olist 58MB)
