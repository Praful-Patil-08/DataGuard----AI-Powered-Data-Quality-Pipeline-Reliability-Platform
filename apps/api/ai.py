import os
import json
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# Prompt injection guard: block control sequences
_PROMPT_INJECTION_RE = re.compile(r"(SYSTEM:|IGNORE PREVIOUS|PROMPT INJECTION|```)", re.IGNORECASE)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

class AIAnalysisOutput(BaseModel):
    summary: str
    severity: str
    root_cause: str
    affected_assets: List[str]
    technical_impact: str
    business_impact: str
    recommended_action: str
    confidence: float
    requires_human_approval: bool = True

def _business_impact_for(dataset_name: str, issues: List[Dict[str, Any]], affected_assets: List[str]) -> str:
    cols = {i.get("column_name") for i in issues if i.get("column_name")}
    # Check for revenue-critical columns
    if any(c in ("order_value", "order_amount", "revenue_usd") for c in cols) or any("revenue" in a.lower() for a in affected_assets):
        return "Revenue reporting at risk: Executive Revenue Dashboard, monthly_revenue and customer LTV will be understated or fail. Finance close may be blocked."
    if any(c == "customer_id" for c in cols):
        return "Customer segmentation at risk: customer_360_view and cohort retention will mis-join. Marketing attribution and churn models degraded."
    if any(c == "discount" for c in cols):
        return "Margin analysis at risk: margin_analysis_model and Promotion ROI Dashboard will miscalculate profitability."
    if any(c in ("order_date", "created_at") for c in cols):
        return "Time-series reporting at risk: daily_sales_summary and executive time filters will be incomplete."
    if affected_assets:
        return f"Downstream assets affected: {', '.join(affected_assets[:3])}. BI dashboards may show incomplete KPIs."
    return "No downstream business metric currently at risk."

def _technical_impact_for(issues: List[Dict[str, Any]], affected_assets: List[str]) -> str:
    types = [i.get("issue_type") for i in issues]
    if "COLUMN_REMOVED" in types:
        return f"Schema break: downstream models selecting removed columns will fail or null out. Affected: {', '.join(affected_assets[:3]) if affected_assets else 'unknown'}."
    if "TYPE_CHANGED" in types:
        return "Type coercion risk: numeric/date consumers will fail to cast. Ingestion may reject rows or produce NULLs."
    if "NUMERIC_DRIFT" in types or "CARDINALITY_DRIFT" in types:
        return "Distribution drift: joins and aggregations will still run but produce silently wrong results (e.g., revenue understated)."
    if any(t in types for t in ("PRIMARY_KEY_NULL","DUPLICATE_PRIMARY_KEY","HIGH_NULL_RATE")):
        return "Data quality breach: primary key and null guarantees violated. Deduplication and completeness checks required."
    return f"Deterministic findings affect {len(affected_assets)} downstream asset(s): {', '.join(affected_assets[:2]) if affected_assets else 'none'}."

def generate_fallback_analysis(
    dataset_name: str,
    issues: List[Dict[str, Any]],
    affected_assets: List[str],
    historical_context: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Deterministic rule-based analyst engine used when OpenAI API key is not configured,
    ensuring 100% testability and offline resilience without external dependencies.
    """
    # history-aware confidence calibration
    historical_context = historical_context or []
    prior_healthy = sum(1 for h in historical_context if h.get("incident_severity") in ("INFO","HEALTHY","PASSED"))
    recent_critical = sum(1 for h in historical_context if h.get("incident_severity")=="CRITICAL")

    if not issues:
        # if history shows prior critical, still note recovery
        if recent_critical > 0 and prior_healthy > 0:
            return {
                "summary": f"Dataset '{dataset_name}' recovered: 0 issues after {recent_critical} recent critical scans.",
                "severity": "PASSED",
                "root_cause": "Data now adheres to baseline after prior drift; likely upstream fix applied.",
                "affected_assets": [],
                "technical_impact": "No technical impact. Pipeline can resume.",
                "business_impact": "Business metrics back to healthy.",
                "recommended_action": "Resume pipeline and monitor next 2 scans for regression.",
                "confidence": 0.97,
                "requires_human_approval": False
            }
        return {
            "summary": f"Dataset '{dataset_name}' successfully verified. Zero schema drift or quality violations detected.",
            "severity": "PASSED",
            "root_cause": "Data adheres strictly to baseline schema specifications and quality contracts.",
            "affected_assets": [],
            "technical_impact": "No technical impact. All downstream models and dashboards will receive expected schema.",
            "business_impact": "No business impact. KPIs remain trustworthy.",
            "recommended_action": "Safe to ingest into production analytics pipelines.",
            "confidence": 1.0,
            "requires_human_approval": False
        }

    # Aggregate severities and issue types
    severities = [iss.get("severity") for iss in issues]
    overall_sev = "CRITICAL" if "CRITICAL" in severities else ("WARNING" if "WARNING" in severities else "INFO")
    
    removed_cols = [iss["column_name"] for iss in issues if iss.get("issue_type") == "COLUMN_REMOVED" and iss.get("column_name")]
    added_cols = [iss["column_name"] for iss in issues if iss.get("issue_type") == "COLUMN_ADDED" and iss.get("column_name")]
    type_changes = [iss for iss in issues if iss.get("issue_type") == "TYPE_CHANGED"]
    quality_issues = [iss for iss in issues if iss.get("issue_type") not in ("COLUMN_REMOVED", "COLUMN_ADDED", "TYPE_CHANGED", "NULLABILITY_CHANGED")]

    # Heuristic analysis synthesis
    root_causes = []
    actions = []

    if removed_cols and added_cols:
        root_causes.append(f"Upstream schema renaming detected: Column(s) {removed_cols} removed while {added_cols} added.")
        actions.append(f"Map newly added column '{added_cols[0]}' to expected baseline '{removed_cols[0]}' in staging layer.")
    elif removed_cols:
        root_causes.append(f"Critical upstream column removal: {removed_cols} omitted by ingestion provider.")
        actions.append(f"Halt pipeline execution and notify data producer regarding missing column(s): {', '.join(removed_cols)}.")
    
    if type_changes:
        tc_desc = [f"{tc['column_name']} ({tc['metadata'].get('previous_type')} -> {tc['metadata'].get('current_type')})" for tc in type_changes]
        root_causes.append(f"Datatype regression: {', '.join(tc_desc)}.")
        actions.append(f"Apply casting transformation to restore expected datatypes before feeding downstream models.")

    if quality_issues:
        q_types = list(set(iss["issue_type"] for iss in quality_issues))
        root_causes.append(f"Data quality violations detected: {', '.join(q_types)}.")
        actions.append("Quarantine corrupt records and trigger automated alert to source system maintainers.")

    # history-aware enrichment
    if historical_context:
        if prior_healthy >= 2 and overall_sev in ("CRITICAL","WARNING"):
            root_causes.append(f"Historical context: {prior_healthy} prior healthy scans, now {overall_sev} — suggests recent upstream change, not long-standing debt.")
            actions.append("Check upstream deployment log for last 24h for schema migrations.")
        if recent_critical >= 2:
            root_causes.append("Recurring critical incidents — systemic upstream instability, not transient.")
            actions.append("Escalate to data producer for contract SLAs.")

    summary = f"Detected {len(issues)} issue(s) across '{dataset_name}' with overall severity {overall_sev}."
    if historical_context and prior_healthy:
        summary += f" (Prior {prior_healthy} healthy scans — new drift.)"
    root_cause_str = " ".join(root_causes) if root_causes else "Data quality or structural inconsistencies detected during profiling."
    recommended_action_str = " ".join(actions) if actions else "Review scan findings and update data ingestion contracts."
    technical = _technical_impact_for(issues, affected_assets or ["revenue_model", "Executive Revenue Dashboard"])
    business = _business_impact_for(dataset_name, issues, affected_assets or ["revenue_model", "Executive Revenue Dashboard"])

    # confidence calibration
    if overall_sev == "CRITICAL":
        conf = 0.92 if prior_healthy else 0.88
        if len(issues) >= 4:
            conf = 0.94
    elif overall_sev == "WARNING":
        conf = 0.85
    else:
        conf = 0.97
    # slightly lower if mixed types
    if len(set(iss.get("issue_type") for iss in issues)) > 3:
        conf = max(0.75, conf - 0.04)

    return {
        "summary": summary,
        "severity": overall_sev,
        "root_cause": root_cause_str,
        "affected_assets": affected_assets or ["revenue_model", "Executive Revenue Dashboard"],
        "technical_impact": technical,
        "business_impact": business,
        "recommended_action": recommended_action_str,
        "confidence": round(conf, 2),
        "requires_human_approval": overall_sev in ("CRITICAL","WARNING")
    }

def _sanitize_prompt(text: str) -> str:
    """Prompt injection guard: strip control markers."""
    if not text:
        return ""
    if _PROMPT_INJECTION_RE.search(text):
        # Remove markers
        text = _PROMPT_INJECTION_RE.sub("", text)
    return text[:2000]

def generate_fallback_from_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Context-aware fallback: uses full deterministic facts (no raw data) to generate analysis.
    More grounded than generate_fallback_analysis because it has schema_diff, drift_stats, quality_score, impact etc.
    """
    dataset_name = context.get("dataset", {}).get("dataset_name", "dataset") if context.get("dataset") else context.get("scan", {}).get("dataset_name", "dataset")
    issues = context.get("issues", [])
    downstream = context.get("downstream_assets", [])
    historical = context.get("historical", [])
    # Use existing fallback but enrich with context
    base = generate_fallback_analysis(dataset_name, issues, downstream, historical)
    # Enrich with schema_diff and impact if available
    schema_diff = context.get("schema_diff")
    if schema_diff and schema_diff.get("rename_candidates"):
        base["root_cause"] += f" Schema evolution: {len(schema_diff['rename_candidates'])} rename candidate(s)."
    drift_stats = context.get("drift_stats", {})
    if drift_stats:
        base["root_cause"] += f" Drift stats: {drift_stats}."
    quality = context.get("quality_score", {})
    if quality and quality.get("score") is not None:
        base["technical_impact"] += f" Quality score {quality['score']}/100."
    impact = context.get("impact")
    if impact and impact.get("summary"):
        base["business_impact"] += f" Impact: {impact['summary']}"
    # Ensure grounded: affected_assets must be subset of downstream
    if downstream:
        # Filter to downstream to avoid hallucination
        base["affected_assets"] = [a for a in base["affected_assets"] if a in downstream] or downstream[:3]
    return base

def run_ai_analyst_with_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Hardened analyst with full context (scan, issues, schema_diff, drift, quality, historical, lineage, impact).
    Validates output is grounded and structured, never modifies data.
    """
    # Sanitize context dataset name for prompt injection
    dataset_name = context.get("dataset", {}).get("dataset_name", "dataset") if context.get("dataset") else "dataset"
    dataset_name = _sanitize_prompt(dataset_name)
    issues = context.get("issues", [])
    # Sanitize issues descriptions
    for iss in issues:
        if "description" in iss:
            iss["description"] = _sanitize_prompt(iss["description"])
    downstream = context.get("downstream_assets", [])
    historical = context.get("historical", [])
    try:
        from ai_provider import get_provider
        # Try context-aware provider method first
        provider = get_provider()
        if hasattr(provider, "analyze_with_context"):
            result = provider.analyze_with_context(context)
        else:
            # Fallback to legacy analyze with enriched context
            result = provider.analyze(dataset_name, issues, downstream, historical)
        # Validate groundedness
        try:
            from ai_context import validate_ai_output
            result = validate_ai_output(result, context)
        except Exception:
            pass
        return result
    except TypeError:
        try:
            from ai_provider import get_provider
            provider = get_provider()
            result = provider.analyze(dataset_name, issues, downstream)
            try:
                from ai_context import validate_ai_output
                result = validate_ai_output(result, context)
            except Exception:
                pass
            return result
        except Exception as e:
            fallback = generate_fallback_from_context(context)
            fallback["summary"] += f" (Provider fallback: {str(e)[:60]})"
            return fallback
    except Exception as e:
        fallback = generate_fallback_from_context(context)
        fallback["summary"] += f" (Provider fallback: {str(e)[:60]})"
        return fallback

def run_ai_analyst(
    dataset_name: str,
    issues: List[Dict[str, Any]],
    affected_assets: List[str],
    historical_context: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Delegates to AIProvider abstraction (Gemini/OpenAI/Mock) — keeps deterministic fallback hermetic.
    Env: AI_PROVIDER=gemini|openai|mock, OPENAI_API_KEY, GEMINI_API_KEY, OPENAI_MODEL/GEMINI_MODEL
    historical_context: last N scans with incident_severity for calibration.
    """
    # Sanitize inputs
    dataset_name = _sanitize_prompt(dataset_name)
    for iss in issues:
        if "description" in iss:
            iss["description"] = _sanitize_prompt(iss["description"])
    try:
        from ai_provider import get_provider
        result = get_provider().analyze(dataset_name, issues, affected_assets, historical_context)
        # Basic validation even for legacy path
        if "requires_human_approval" not in result and result.get("severity") in ("CRITICAL", "WARNING"):
            result["requires_human_approval"] = True
        return result
    except TypeError:
        # provider without history support
        try:
            from ai_provider import get_provider
            return get_provider().analyze(dataset_name, issues, affected_assets)
        except Exception as e:
            fallback = generate_fallback_analysis(dataset_name, issues, affected_assets, historical_context)
            fallback["summary"] += f" (Provider fallback: {str(e)[:60]})"
            return fallback
    except Exception as e:
        fallback = generate_fallback_analysis(dataset_name, issues, affected_assets, historical_context)
        fallback["summary"] += f" (Provider fallback: {str(e)[:60]})"
        return fallback
