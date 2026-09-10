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

### `schema_columns`
- `id`: UUID / Integer (Primary Key)
- `schema_id`: FK -> `schemas.id`
- `column_name`: VARCHAR(255)
- `data_type`: VARCHAR(50) (INTEGER, FLOAT, STRING, DATE, BOOLEAN)
- `nullable`: BOOLEAN
- `unique_count`: INTEGER
- `null_count`: INTEGER
- `sample_values`: JSONB

### `scans`
- `id`: UUID / Integer (Primary Key)
- `dataset_id`: FK -> `datasets.id`
- `status`: VARCHAR(50) ('RUNNING', 'COMPLETED', 'FAILED')
- `healthy_count`: INTEGER DEFAULT 0
- `warning_count`: INTEGER DEFAULT 0
- `critical_count`: INTEGER DEFAULT 0
- `started_at`: TIMESTAMP WITH TIME ZONE
- `completed_at`: TIMESTAMP WITH TIME ZONE

### `issues`
- `id`: UUID / Integer (Primary Key)
- `scan_id`: FK -> `scans.id`
- `issue_type`: VARCHAR(100) (COLUMN_REMOVED, COLUMN_ADDED, TYPE_CHANGED, NULLABILITY_CHANGED, NULL_CHECK, DUPLICATE_CHECK, RANGE_CHECK, DATE_VALIDATION, CATEGORICAL_INCONSISTENCY, NUMERIC_ANOMALY)
- `severity`: VARCHAR(20) ('CRITICAL', 'WARNING', 'INFO')
- `column_name`: VARCHAR(255) (Nullable)
- `description`: TEXT
- `metadata`: JSONB

### `ai_analysis`
- `id`: UUID / Integer (Primary Key)
- `scan_id`: FK -> `scans.id` (or issue_id)
- `summary`: TEXT
- `root_cause`: TEXT
- `impact`: TEXT
- `affected_assets`: JSONB
- `recommendation`: TEXT
- `confidence`: FLOAT
- `created_at`: TIMESTAMP WITH TIME ZONE

### `remediations`
- `id`: UUID / Integer (Primary Key)
- `issue_id`: FK -> `issues.id` (Nullable)
- `scan_id`: FK -> `scans.id`
- `suggestion`: TEXT
- `status`: VARCHAR(50) ('PENDING', 'APPROVED', 'REJECTED')
- `decision_by`: VARCHAR(255)
- `decision_at`: TIMESTAMP WITH TIME ZONE
- `notes`: TEXT

### `dependencies` (Lineage)
- `id`: UUID / Integer (Primary Key)
- `source_asset`: VARCHAR(255) (e.g. `orders.order_value`)
- `target_asset`: VARCHAR(255) (e.g. `revenue_model`)
- `relationship_type`: VARCHAR(50) (e.g. `DERIVED_BY`, `USED_BY_DASHBOARD`)
