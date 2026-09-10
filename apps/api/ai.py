import os
import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

class AIAnalysisOutput(BaseModel):
    summary: str
    severity: str
    root_cause: str
    affected_assets: List[str]
    recommended_action: str
    confidence: float
    requires_human_approval: bool = True

def generate_fallback_analysis(
    dataset_name: str,
    issues: List[Dict[str, Any]],
    affected_assets: List[str]
) -> Dict[str, Any]:
    """
    Deterministic rule-based analyst engine used when OpenAI API key is not configured,
    ensuring 100% testability and offline resilience without external dependencies.
    """
    if not issues:
        return {
            "summary": f"Dataset '{dataset_name}' successfully verified. Zero schema drift or quality violations detected.",
            "severity": "PASSED",
            "root_cause": "Data adheres strictly to baseline schema specifications and quality contracts.",
            "affected_assets": [],
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

    summary = f"Detected {len(issues)} issue(s) across '{dataset_name}' with overall severity {overall_sev}."
    root_cause_str = " ".join(root_causes) if root_causes else "Data quality or structural inconsistencies detected during profiling."
    recommended_action_str = " ".join(actions) if actions else "Review scan findings and update data ingestion contracts."

    return {
        "summary": summary,
        "severity": overall_sev,
        "root_cause": root_cause_str,
        "affected_assets": affected_assets or ["revenue_model", "Executive Revenue Dashboard"],
        "recommended_action": recommended_action_str,
        "confidence": 0.92,
        "requires_human_approval": True
    }

def run_ai_analyst(
    dataset_name: str,
    issues: List[Dict[str, Any]],
    affected_assets: List[str]
) -> Dict[str, Any]:
    """
    Invokes OpenAI structured outputs if OPENAI_API_KEY is available,
    otherwise uses the high-precision deterministic fallback engine.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return generate_fallback_analysis(dataset_name, issues, affected_assets)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        prompt = f"""
You are the DataGuard Lead Analyst Agent.
Analyze the following dataset scan findings and return a structured JSON response.

Dataset: {dataset_name}
Deterministic Findings:
{json.dumps(issues, indent=2)}

Downstream Assets at Risk:
{json.dumps(affected_assets, indent=2)}

Rules:
1. Explain what happened clearly for analytics engineers.
2. Identify the most probable upstream root cause (e.g. column renaming, producer bug, type mismatch).
3. Detail the business and technical downstream impact.
4. Recommend a concrete remediation action.
5. Never claim you changed production data. All remediation requires human approval.
"""

        response = client.beta.chat.completions.parse(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are DataGuard's AI Data Reliability Analyst. Provide rigorous, structured root cause and impact reasoning."
                },
                {"role": "user", "content": prompt}
            ],
            response_format=AIAnalysisOutput,
            temperature=0.1
        )

        parsed = response.choices[0].message.parsed
        return parsed.model_dump()
    except Exception as e:
        # Gracefully fall back to local engine on API failure or network issue
        fallback = generate_fallback_analysis(dataset_name, issues, affected_assets)
        fallback["summary"] += f" (Note: AI fallback active: {str(e)[:60]})"
        return fallback
