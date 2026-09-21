# DataGuard Roadmap

## MVP (Current Target) — Completed
- **Phase 1**: Architecture & Spec Review
- **Phase 2**: Application Foundation (Next.js, FastAPI, PostgreSQL config, Docker Compose)
- **Phase 3**: Dataset Upload (CSV/JSON ingestion, metadata profiling)
- **Phase 4**: Deterministic Schema Profiling (types, nulls, unique count, fingerprints)
- **Phase 5**: Deterministic Schema Drift Engine (detect ADDED, REMOVED, TYPE_CHANGED, NULLABILITY_CHANGED + Watchtower null/cardinality/numeric/row drifts)
- **Phase 6**: Deterministic Data Quality Engine (null rate, duplicate keys, range, dates, categorical) → **Phase 1 Refactor 2026-09**: modular `quality/` registry (8 rules, Great Expectations/Soda-native pattern)
- **Phase 7**: Scan Dashboard & Frontend UI (Next.js App router, schema diffs, quality tables + HealthCards/ReliabilityTrend/TopIssues/BusinessImpact)
- **Phase 8**: OpenAI Analyst Agent (structured explanations, root cause, recommendations with mock/openai/gemini provider)
- **Phase 9**: Downstream Impact Analysis (Column -> SQL Model -> Dashboard DAG via `lineage_config.json`)
- **Phase 10**: Human Approval Workflow (Approve/Reject actions, audit logging)
- **Phase 11**: Demo datasets & end-to-end verification (Olist 9 CSVs + 3 interactive demo buttons)

## Next — Master Improvement Plan (18 Phases)
- **Phase 1 — Quality Rule Engine** ✅ *Done 2026-09-22*: `quality/` package with `QualityRule`/`RuleResult`/`QualityRuleRegistry`/`QualityEngine`, 8 isolated rules, façade `run_quality_checks()` — no breaking change, 17 tests green.
- **Phase 2 — Quality Contracts**: declarative thresholds per dataset (SodaCL-style), versioned, stored, testable.
- **Phase 3 — Quality Score**: deterministic 0-100 with dimensions (completeness/validity/uniqueness/consistency/freshness/schema stability).
- **Phase 4 — Schema Evolution**: rename detection with evidence scoring, historical schema versions.
- **Phase 5 — Statistical Drift**: PSI/KS/JS per data type, evidence-backed thresholds.
- **Phase 6 — Baselines**: explicit Baseline model (select/compare/update, versioned, never silent).
- **Phase 7 — Incident Correlation**: incident layer grouping related findings deterministically.
- **Phase 8 — Real Lineage**: Dataset/Job/Run/Column graph with traversal (OpenLineage/Marquez reference, lightweight).
- **Phase 9 — Impact Analysis**: recursive downstream severity propagation.
- **Phase 10 — Historical Reliability**: historical observations feeding trends/anomaly.
- **Phase 11 — Anomaly Detection**: historical deviation detection with evidence.
- **Phase 12 — AI Analyst hardening**: context builder + structured output + prompt-injection guard.
- **Phase 13 — Scoped RAG** (only if justified): dataset/incident-scoped retrieval.
- **Phase 14 — Remediation + Audit polish**: approval workflow hardening.
- **Phase 15 — Performance & Security**: chunked processing, upload validation, secrets audit.
- **Phase 16 — Frontend polish**: incident-first dashboard, quality score viz.
- **Phase 17 — Documentation + Demo story polish**

## V2 (Orchestration & Advanced Operations)
- Phase 12: Apache Airflow DAG integration (DataGuard check operator)
- Phase 13: Slack / Email Webhook Alerts
- Phase 14: Automated blocking in CI/CD data pipelines

## V3 (Enterprise Knowledge & RAG)
- Phase 15: RAG with business metric definitions and schema playbooks
- Phase 16: Automated PR generation for schema migration shims
