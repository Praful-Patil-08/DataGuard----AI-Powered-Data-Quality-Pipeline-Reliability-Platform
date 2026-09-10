# DataGuard DRE (Detailed Requirements Engineering)

## Functional Requirements

- **FR-01**: The system shall accept CSV files.
- **FR-02**: The system shall accept JSON files.
- **FR-03**: The system shall deterministically profile uploaded datasets (types, nulls, unique count, sample values).
- **FR-04**: The system shall detect missing/removed columns compared to baseline.
- **FR-05**: The system shall detect newly added columns.
- **FR-06**: The system shall detect datatype changes.
- **FR-07**: The system shall detect nullability changes.
- **FR-08**: The system shall detect duplicate records and primary key violations.
- **FR-09**: The system shall detect invalid values (negative ranges, malformed dates).
- **FR-10**: The system shall detect configurable data-quality violations (categorical inconsistencies, numeric outliers).
- **FR-11**: The system shall assign deterministic severity (CRITICAL, WARNING, INFO).
- **FR-12**: The system shall store scan history and audit trail.
- **FR-13**: The system shall generate structured AI explanations and root causes using OpenAI.
- **FR-14**: The system shall generate human-reviewable remediation suggestions.
- **FR-15**: The system shall trace and identify downstream impact (SQL models, dashboards).
- **FR-16**: The system shall allow users to approve or reject remediation suggestions and record the decision.

## Non-Functional Requirements

- **NFR-01**: API response times must remain performant for supported dataset sizes (up to 100MB in MVP).
- **NFR-02**: API keys (OPENAI_API_KEY) must strictly reside on backend environment variables, never sent to frontend.
- **NFR-03**: AI recommendations must not execute automatic changes to storage or production data.
- **NFR-04**: Scan results and audit trails must be deterministic, reproducible, and auditable.
- **NFR-05**: All deterministic quality and schema checks must function completely without an LLM.
- **NFR-06**: AI responses must use structured JSON schemas (via Pydantic or structured output).
- **NFR-07**: User-facing error messages must be clear, actionable, and fail-safe.

## Security Requirements

- Uploaded files must be validated for extension, MIME type, and size limits.
- Sanitize file names to prevent directory traversal attacks.
- No arbitrary code or SQL execution.
- Only metadata, statistics, and sample values are sent to LLM; never send full raw datasets to external AI services.
- Remediation approvals must be recorded with user identity, decision status, and timestamp.
