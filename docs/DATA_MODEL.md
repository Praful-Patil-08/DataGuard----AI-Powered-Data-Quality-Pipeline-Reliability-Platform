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

### `scans` (with incident + gate)
- `id`: UUID / Integer (Primary Key)
- `dataset_id`: FK -> `datasets.id`
- `baseline_dataset_id`: FK -> `datasets.id` nullable (explicit baseline, replaces fuzzy `like`)
- `status`: VARCHAR(50) ('RUNNING', 'COMPLETED', 'FAILED')
- `healthy_count`: INTEGER
- `warning_count`: INTEGER
- `critical_count`: INTEGER
- `incident_summary`: TEXT (Watchtower `_incident_report` human-friendly)
- `incident_severity`: VARCHAR(20) (INFO/WARNING/CRITICAL/PASSED)
- `started_at`/`completed_at`: TIMESTAMP

### `issues`
- `id`: UUID / Integer (Primary Key)
- `scan_id`: FK -> `scans.id`
- `issue_type`: VARCHAR(100) (COLUMN_REMOVED, COLUMN_ADDED, TYPE_CHANGED, NULLABILITY_CHANGED, NULL_CHECK, DUPLICATE_CHECK, RANGE_CHECK, DATE_VALIDATION, CATEGORICAL_INCONSISTENCY, NUMERIC_ANOMALY)
- `severity`: VARCHAR(20) ('CRITICAL', 'WARNING', 'INFO')
- `column_name`: VARCHAR(255) (Nullable)
- `description`: TEXT
- `metadata`: JSONB

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

### `storage` + migrations
- `storage_backend.py`: `local` `storage/{id}_{filename}` → `s3://` if `STORAGE_BACKEND=s3` (boto3 optional)
- `database.py:run_migrations()` additive `ALTER TABLE` on startup (covers `scans`/`schema_columns`/`ai_analysis`), 100MB upload limit (handles Olist 58MB)
