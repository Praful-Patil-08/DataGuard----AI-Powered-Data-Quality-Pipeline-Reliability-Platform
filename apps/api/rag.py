"""
Scoped RAG — justified, not generic chatbot.

Scope: only retrieve docs relevant to current dataset/scan/incident/lineage/history.
Knowledge: dataset docs, contracts, incident history, runbooks, schema docs, business definitions.
Stored in knowledge_base.json (8 docs). Retrieval via keyword scoring (no vector DB, deterministic, testable).

Design: For a given scan/dataset/column/issue_types, score each doc via:
- dataset match (exact or prefix) +2
- column match +2
- issue_type match +2
- tag overlap +1 per tag
- business keyword (revenue, customer, etc.) +1
Return top-k sorted by score, only if score >0.

No external dependency, no hallucination, scoped, explainable.
"""
from typing import List, Dict, Any, Optional
import json
from pathlib import Path

KB_PATH = Path(__file__).parent / "knowledge_base.json"

def _load_kb() -> List[Dict[str, Any]]:
    try:
        if KB_PATH.exists():
            return json.loads(KB_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def _score_doc(doc: Dict[str, Any], dataset: Optional[str], column: Optional[str], issue_types: List[str], query: Optional[str] = None) -> int:
    score = 0
    ds = (dataset or "").lower()
    col = (column or "").lower()
    q = (query or "").lower()
    doc_ds = (doc.get("dataset") or "").lower()
    doc_col = (doc.get("column") or "").lower()
    doc_issue = (doc.get("issue_type") or "").lower()
    # Dataset match
    if doc_ds and doc_ds != "*" and ds:
        if doc_ds == ds or ds.startswith(doc_ds) or doc_ds.startswith(ds.split("_")[0] if "_" in ds else ds):
            score += 3
        elif doc_ds in ds or ds in doc_ds:
            score += 1
    elif doc_ds == "*":
        score += 0  # generic docs score lower unless other matches
    # Column match
    if doc_col and doc_col != "*" and col:
        if doc_col == col:
            score += 3
        elif doc_col in col or col in doc_col:
            score += 1
    elif doc_col == "*":
        pass
    # Issue type match
    for it in issue_types:
        it_l = it.lower()
        if doc_issue and doc_issue != "*" and it_l:
            if doc_issue == it_l:
                score += 3
            elif doc_issue in it_l or it_l in doc_issue:
                score += 1
    # Tag overlap with query/issue_types/col
    tags = [t.lower() for t in doc.get("tags", [])]
    for tag in tags:
        if tag in col or col in tag:
            score += 1
        if any(tag in it.lower() for it in issue_types):
            score += 1
        if q and tag in q:
            score += 1
        if tag in ds:
            score += 1
    # Business keyword in query
    if q:
        for kw in ["revenue", "customer", "margin", "discount", "order"]:
            if kw in q and kw in json.dumps(doc).lower():
                score += 1
    return score

def retrieve(
    dataset: Optional[str] = None,
    column: Optional[str] = None,
    issue_types: Optional[List[str]] = None,
    query: Optional[str] = None,
    k: int = 3,
    min_score: int = 1,
) -> List[Dict[str, Any]]:
    """
    Scoped retrieval: only returns docs with score >= min_score, sorted desc, top-k.
    Deterministic, no vector DB. Sanitizes inputs to prevent prompt injection leakage.
    """
    import re
    _san_re = re.compile(r"[^a-zA-Z0-9_\-\.\s]")
    def _san(v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        cleaned = _san_re.sub("", v)[:100]
        for m in ["SYSTEM:", "SYSTEM", "IGNORE", "PROMPT", "```", "{{", "}}"]:
            cleaned = cleaned.replace(m, "")
        return cleaned
    dataset_s = _san(dataset)
    column_s = _san(column)
    query_s = _san(query) if query else None
    issue_types_s = [_san(it) for it in (issue_types or []) if it]
    issue_types = issue_types_s
    kb = _load_kb()
    scored: List[tuple[int, Dict[str, Any]]] = []
    for doc in kb:
        score = _score_doc(doc, dataset_s, column_s, issue_types, query_s)
        if score >= min_score:
            scored.append((score, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    # Return docs with score, truncated
    result = []
    for score, doc in scored[:k]:
        result.append({**doc, "_score": score, "_why": f"Matched dataset={dataset_s}, column={column_s}, issue_types={issue_types}"})
    return result

def retrieve_for_scan(
    dataset_name: str,
    issues: List[Dict[str, Any]],
    downstream_assets: Optional[List[str]] = None,
    k: int = 3,
) -> List[Dict[str, Any]]:
    """Convenience for scan: aggregate issue_types and columns, retrieve top-k across all."""
    issue_types = list(set(i.get("issue_type") for i in issues if i.get("issue_type")))
    # Prioritize columns from critical issues
    critical_cols = [i.get("column_name") for i in issues if i.get("severity") == "CRITICAL" and i.get("column_name")]
    col = critical_cols[0] if critical_cols else (issues[0].get("column_name") if issues else None)
    if col and " -> " in col:
        col = col.split(" -> ")[0]
    # Query is dataset + issue types
    query = f"{dataset_name} {' '.join(issue_types)}"
    return retrieve(dataset=dataset_name, column=col, issue_types=issue_types, query=query, k=k)

def retrieve_for_context(context: Dict[str, Any], k: int = 3) -> List[Dict[str, Any]]:
    """Retrieve for AI context (scan, dataset, issues, lineage)."""
    dataset = context.get("dataset", {}).get("dataset_name") if context.get("dataset") else context.get("scan", {}).get("dataset_name")
    issues = context.get("issues", [])
    downstream = context.get("downstream_assets", [])
    # Use scan-based retrieval
    return retrieve_for_scan(dataset or "unknown", issues, downstream, k=k)
