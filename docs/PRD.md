# DataGuard PRD

## 1. Product Overview

DataGuard is an AI-powered data reliability assistant that detects schema drift and data-quality problems before they propagate into analytics systems.

## 2. Problem

Data pipelines can successfully execute while producing incorrect or structurally incompatible data.

Common problems:
- Renamed columns
- Removed columns
- Added columns
- Datatype changes
- Null values
- Duplicate records
- Invalid values
- Unexpected distributions
- Inconsistent categorical values
- Pipeline failures

These issues affect downstream SQL models, dashboards, and business decision-making.

## 3. Target Users

Primary:
- Data Analysts
- Analytics Engineers
- Data Engineers

Secondary:
- BI Developers
- Engineering Teams

## 4. MVP Scope

DataGuard must:
1. Accept CSV and JSON datasets.
2. Profile datasets deterministically.
3. Generate schema fingerprints.
4. Compare current schema against baseline.
5. Detect schema drift (added, removed, type changed, nullability changed).
6. Run configurable deterministic data-quality checks.
7. Assign deterministic severity (CRITICAL, WARNING, INFO).
8. Explain detected problems with an OpenAI Agent.
9. Identify downstream impact across models & dashboards.
10. Suggest remediations.
11. Allow human approval or rejection with audit logging.
12. Store scan history.

## 5. Out of Scope for MVP

MVP will NOT:
- Automatically modify production databases.
- Connect to live Shopify/Meta or warehouse systems.
- Automatically deploy pipeline changes.
- Run unrestricted SQL.
- Automatically fix production data without human consent.

## 6. Success Criteria

A user can:
Upload dataset → Scan → View deterministic issues → See downstream impact → Receive AI root cause & recommendation → Approve/reject recommendation → Review audit trail.
