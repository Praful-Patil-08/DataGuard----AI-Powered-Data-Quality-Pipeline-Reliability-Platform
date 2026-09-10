"""
AIProvider abstraction — allows switching between OpenAI, Gemini, Mock without coupling.
MVP uses Mock/Fallback by default if no key is set; OpenAI if OPENAI_API_KEY set;
Gemini if GEMINI_API_KEY or AI_PROVIDER=gemini is set.
"""
import os
from typing import List, Dict, Any
from abc import ABC, abstractmethod

class AIProvider(ABC):
    @abstractmethod
    def analyze(self, dataset_name: str, issues: List[Dict[str, Any]], affected_assets: List[str], historical_context=None) -> Dict[str, Any]:
        pass

class MockProvider(AIProvider):
    def analyze(self, dataset_name: str, issues: List[Dict[str, Any]], affected_assets: List[str], historical_context=None) -> Dict[str, Any]:
        from ai import generate_fallback_analysis
        return generate_fallback_analysis(dataset_name, issues, affected_assets, historical_context)

class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o")
    def analyze(self, dataset_name: str, issues: List[Dict[str, Any]], affected_assets: List[str], historical_context=None) -> Dict[str, Any]:
        if not self.api_key:
            return MockProvider().analyze(dataset_name, issues, affected_assets, historical_context)
        try:
            from openai import OpenAI
            from ai import AIAnalysisOutput
            import json
            client = OpenAI(api_key=self.api_key)
            hist_txt = f"Historical context (last {len(historical_context)} scans): {json.dumps(historical_context, indent=2)}" if historical_context else "No historical context."
            prompt = f"""You are DataGuard Lead Analyst. Return JSON with summary, severity, root_cause, technical_impact, business_impact, affected_assets, recommended_action, confidence.
Dataset: {dataset_name}
Findings: {json.dumps(issues, indent=2)}
Assets: {json.dumps(affected_assets, indent=2)}
{hist_txt}
Rules: explain what happened, root cause hypothesis (use history to note if new drift after healthy period), technical and business impact separately, concrete remediation, never claim you changed data."""
            response = client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are DataGuard AI Data Reliability Analyst. Provide rigorous structured reasoning with technical_impact and business_impact."},
                    {"role": "user", "content": prompt}
                ],
                response_format=AIAnalysisOutput,
                temperature=0.1
            )
            return response.choices[0].message.parsed.model_dump()
        except Exception as e:
            fallback = MockProvider().analyze(dataset_name, issues, affected_assets, historical_context)
            fallback["summary"] += f" (OpenAI fallback: {str(e)[:60]})"
            return fallback

class GeminiProvider(AIProvider):
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    def analyze(self, dataset_name: str, issues: List[Dict[str, Any]], affected_assets: List[str], historical_context=None) -> Dict[str, Any]:
        if not self.api_key:
            return MockProvider().analyze(dataset_name, issues, affected_assets, historical_context)
        try:
            import google.generativeai as genai
            import json
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model)
            hist_txt = f"History: {json.dumps(historical_context)}" if historical_context else ""
            prompt = f"""Dataset: {dataset_name}
Findings: {json.dumps(issues)}
Assets: {json.dumps(affected_assets)}
{hist_txt}
Return JSON with keys: summary, severity, root_cause, technical_impact, business_impact, affected_assets, recommended_action, confidence, requires_human_approval."""
            resp = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            text = resp.text
            data = json.loads(text)
            # normalize
            data.setdefault("technical_impact", data.get("impact", ""))
            data.setdefault("business_impact", "Business impact derived from affected assets.")
            data.setdefault("affected_assets", affected_assets)
            data.setdefault("confidence", 0.85)
            data.setdefault("requires_human_approval", True)
            return data
        except Exception as e:
            fallback = MockProvider().analyze(dataset_name, issues, affected_assets, historical_context)
            fallback["summary"] += f" (Gemini fallback: {str(e)[:60]})"
            return fallback

def get_provider() -> AIProvider:
    provider = os.getenv("AI_PROVIDER", "").lower()
    if provider == "gemini":
        return GeminiProvider()
    if provider == "openai":
        return OpenAIProvider()
    # auto-detect
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return GeminiProvider()
    if os.getenv("OPENAI_API_KEY"):
        return OpenAIProvider()
    return MockProvider()
