# DataGuard Roadmap

## MVP (Current Target)
- **Phase 1**: Architecture & Spec Review
- **Phase 2**: Application Foundation (Next.js, FastAPI, PostgreSQL config, Docker Compose)
- **Phase 3**: Dataset Upload (CSV/JSON ingestion, metadata profiling)
- **Phase 4**: Deterministic Schema Profiling (types, nulls, unique count, fingerprints)
- **Phase 5**: Deterministic Schema Drift Engine (detect ADDED, REMOVED, TYPE_CHANGED, NULLABILITY_CHANGED)
- **Phase 6**: Deterministic Data Quality Engine (null rate, duplicate keys, range, dates, categorical)
- **Phase 7**: Scan Dashboard & Frontend UI (Next.js App router, schema diffs, quality tables)
- **Phase 8**: OpenAI Analyst Agent (structured explanations, root cause, recommendations with mocked/live OpenAI API)
- **Phase 9**: Downstream Impact Analysis (Column -> SQL Model -> Dashboard DAG)
- **Phase 10**: Human Approval Workflow (Approve/Reject actions, audit logging)
- **Phase 11**: Demo datasets & end-to-end verification

## V2 (Orchestration & Advanced Operations)
- Phase 12: Apache Airflow DAG integration (DataGuard check operator)
- Phase 13: Slack / Email Webhook Alerts
- Phase 14: Automated blocking in CI/CD data pipelines

## V3 (Enterprise Knowledge & RAG)
- Phase 15: RAG with business metric definitions and schema playbooks
- Phase 16: Automated PR generation for schema migration shims
