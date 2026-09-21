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
- **Phase 2 — Quality Contracts** ✅ *Done 2026-09-22*: declarative `QualityContract` table (5 types: completeness/uniqueness/range/regex/row_count, params JSON, threshold 0-1, versioned `version+1`, enabled flag, prefix matching `orders`→`orders_v1`), evaluator `quality_contracts.py` (deterministic pandas, evidence `expected vs actual`), API `POST/GET/PUT/DELETE /api/contracts` + `GET /api/datasets/{id}/contracts` + `POST /api/datasets/{id}/contracts/evaluate`, scan-integrated as `CONTRACT_BREACH_*` issues, 13 tests, total 30 green.
- **Phase 3 — Quality Score** ✅ *Done 2026-09-22*: deterministic `quality_score.py` (7 dims weighted completeness 0.20/uniqueness 0.20/validity 0.20/consistency 0.10/schema 0.15/distribution 0.10/freshness 0.05, penalty CRITICAL -25/WARNING -10, freshness from max date recency), persisted `scans.quality_score/dimensions`, `GET /api/scans/{id}/score` + history `quality_score`, 10 tests, total 40 green.
- **Phase 4 — Schema Evolution** ✅ *Done 2026-09-22*: rename detection `drift.py:_detect_rename_candidates` (difflib + token overlap + type_compat + stat_sim → confidence 0.60 possible/0.75 likely/0.85 very likely, INFO never suppresses `COLUMN_REMOVED`/`COLUMN_ADDED`), historical versions `GET /api/datasets/{id}/schemas` + `.../schema/history` (physical + logical `orders%`) + `.../schema/compare?baseline_dataset_id=` (drift + candidates), 5 tests, total 45 green.
- **Phase 5 — Statistical Drift** ✅ *Done 2026-09-22*: `statistical_drift.py` (PSI via quantile bins / category frequencies, KS via ECDF, JSD via category distributions; thresholds PSI 0.1/0.25, KS 0.2/0.4, JSD 0.1/0.2, sample-size guarded ≥30 rows/≥5 uniques, ≤50 cats) — numeric `PSI+KS` + categorical `PSI+JSD`, each finding with `metric, baseline/current, threshold, severity, evidence, affected column`, integrated into `drift.py:detect_schema_drift(..., baseline_df, current_df)` via scan preload (storage) and `.../schema/compare`, 14 tests, total 59 green.
- **Phase 6 — Baselines** ✅ *Done 2026-09-22*: `Baseline` table (logical `dataset_name`, `baseline_dataset_id/schema_id`, `fingerprint/row_count/column_count/quality_score` snapshot, `version`, `is_active`, `created_by`, never silent), manager `baselines.py` (`_logical_name` prefix, `get_active_baseline`, `create_baseline` with deactivation, `list/activate/compare`), APIs `POST/GET /api/baselines` + `GET/PUT/DELETE /api/baselines/{id}` + `PUT .../activate` + `GET /api/datasets/{id}/baselines` + `GET /api/baselines/{id}/compare/{dataset_id}`, scan uses active baseline when no explicit `baseline_dataset_id` (fallback to prefix), 7 tests, total 66 green.
- **Phase 7 — Incident Correlation** ✅ *Done 2026-09-22*: `Incident` table (`scan_id/dataset_id/dataset_name/title/severity/status/root_cause/affected_columns/affected_assets/issue_ids/issue_types/issue_count/correlation_evidence/quality_score_at_incident`), manager `incidents.py` (`FAMILY_MAP` schema/drift/statistical/quality/contract, `correlate_incidents_for_scan` one per scan deterministic, never LLM, evidence `families/family_counts/overlapping_columns/downstream_assets`), APIs `GET /api/incidents` + `GET/PUT /api/incidents/{id}` + `GET /api/scans/{id}/incidents` + `GET /api/datasets/{id}/incidents`, scan auto-creates incident, 8 tests, total 74 green.
- **Phase 8 — Real Lineage** ✅ *Done 2026-09-22*: `LineageEdge` table (`source_dataset/source_column → target_dataset/target_column` via `job_name/run_id`, `target_type` DATASET/JOB/SQL_MODEL/DASHBOARD, `relationship`, `is_active`), graph `lineage_graph.py` (`_ensure_seeded` from `lineage_config.json`, `create_edge/list_edges`, `get_direct_downstream/upstream`, `traverse_graph` BFS `max_depth` 1-5 with cycle protection, `get_lineage_graph`), APIs `POST/GET/DELETE /api/lineage/edges` + `GET /api/lineage/graph` + `GET /api/lineage/{dataset}/downstream/upstream` + enhanced `GET /api/lineage/{dataset}/{column}` (DB first, `is_demo` for seeded vs custom), 9 tests, total 83 green.
- **Phase 9 — Impact Analysis** ✅ *Done 2026-09-22*: `impact.py` (deterministic `analyze_impact` single column + `analyze_scan_impact` union per scan via `lineage_graph.traverse_graph`, severity decay `CRITICAL@1→WARNING@2→INFO@3`, KPI aggregation `Revenue/Customer/Margin` via `KPI_MAP`, evidence `distance/relationship/evidence`), APIs `GET /api/impact/{dataset}/{column}?severity=&depth=` + `GET /api/impact/{dataset}` + `GET /api/scans/{scan_id}/impact` + `GET /api/incidents/{incident_id}/impact`, 9 tests, total 92 green.
- **Phase 10 — Historical Reliability** ✅ *Done 2026-09-22*: `reliability.py` (Elementary-inspired `get_reliability_trends` per-day `avg_quality_score/critical/warning/healthy/incidents`, `get_most_problematic_datasets` by avg_score/incidents, `get_most_problematic_columns` by issue frequency, `get_incident_frequency`, `detect_quality_degradation` recent 5 vs historical 5 `delta` threshold `-5`, `get_reliability_overview`), APIs `GET /api/reliability/overview|trends|datasets|columns|incidents|degradation`, 7 tests, total 99 green.
- **Phase 11 — Anomaly Detection** ✅ *Done 2026-09-22*: `anomaly.py` (statistical ` _is_anomalous_zscore` `|z|≥2 warning/≥3 critical` n≥5 else IQR `q1-1.5*IQR`, `detect_null_rate_anomalies` via `schema_columns.null_rate` history, `detect_quality_score_anomaly` via `Scan.quality_score`, `detect_row_count_anomaly`, `detect_anomalies_for_scan/dataset` union, evidence `historical_mean/std/current/z/threshold/historical_range/delta`), APIs `GET /api/anomalies?dataset_name=&window=` + `GET /api/datasets/{id}/anomalies` + `GET /api/scans/{id}/anomalies`, no ML, deterministic, 9 tests, total 108 green.
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
