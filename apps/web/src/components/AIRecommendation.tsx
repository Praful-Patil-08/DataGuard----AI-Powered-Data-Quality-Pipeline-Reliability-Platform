import React, { useState } from "react";
import { Sparkles, Check, X, ShieldAlert, CheckCircle2, Bot } from "lucide-react";

interface AIAnalysisProps {
  analysis: {
    id?: number;
    summary: string;
    severity: string;
    root_cause: string;
    impact: string;
    technical_impact?: string | null;
    business_impact?: string | null;
    affected_assets: string[];
    recommended_action: string;
    confidence: number;
    requires_human_approval: boolean;
  };
  remediation?: {
    id: number;
    suggestion: string;
    status: string;
    decision_by?: string;
    decision_at?: string;
  };
  onDecision: (remediationId: number, approved: boolean) => Promise<void>;
}

export const AIRecommendation = ({ analysis, remediation, onDecision }: AIAnalysisProps) => {
  const [loading, setLoading] = useState(false);
  const [currentStatus, setCurrentStatus] = useState(remediation?.status || "PENDING");

  const handleAction = async (approved: boolean) => {
    if (!remediation) return;
    setLoading(true);
    try {
      await onDecision(remediation.id, approved);
      setCurrentStatus(approved ? "APPROVED" : "REJECTED");
    } finally {
      setLoading(false);
    }
  };

  const isApproved = currentStatus === "APPROVED";
  const isRejected = currentStatus === "REJECTED";

  return (
    <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10 shadow-[0_12px_40px_rgba(0,0,0,0.5)] relative overflow-hidden">
      {/* Decorative ambient illumination */}
      <div className="absolute -top-24 -right-24 w-72 h-72 bg-teal-500/5 rounded-full blur-3xl pointer-events-none" />

      <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/95 via-slate-950 to-slate-950 p-6 sm:p-7 shadow-[inset_0_1px_1px_rgba(255,255,255,0.08)]">
        {/* Header Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-5 border-b border-white/[0.08]">
          <div className="flex items-center space-x-3.5">
            <div className="w-10 h-10 rounded-full bg-white/5 border border-white/10 flex items-center justify-center text-teal-300 shadow-[0_0_16px_rgba(20,184,166,0.15)]">
              <Bot className="w-5 h-5 stroke-[2]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-white tracking-tight">
                  DataGuard AI Reliability Analyst
                </h3>
                <span className="text-[10px] px-2.5 py-0.5 rounded-full bg-teal-500/10 text-teal-300 border border-teal-500/20 font-mono font-semibold flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
                  {Math.round(analysis.confidence * 100)}% Confidence
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Deterministic Findings & Root-Cause Diagnosis
              </p>
            </div>
          </div>

          {/* Audit state badge */}
          <div>
            {isApproved ? (
              <span className="px-3.5 py-1.5 rounded-full text-xs font-semibold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> Approved for Production
              </span>
            ) : isRejected ? (
              <span className="px-3.5 py-1.5 rounded-full text-xs font-semibold bg-rose-500/15 text-rose-300 border border-rose-500/30 flex items-center gap-1.5">
                <X className="w-3.5 h-3.5 text-rose-400" /> Remediation Rejected
              </span>
            ) : (
              <span className="px-3.5 py-1.5 rounded-full text-xs font-semibold bg-amber-500/15 text-amber-300 border border-amber-500/30 flex items-center gap-1.5">
                <ShieldAlert className="w-3.5 h-3.5 text-amber-400" /> Human Approval Required
              </span>
            )}
          </div>
        </div>

        {/* Content sections */}
        <div className="mt-6 space-y-4">
          {/* Executive Summary */}
          <div>
            <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">
              Executive Summary
            </span>
            <p className="text-sm text-slate-200 mt-1 leading-relaxed bg-black/40 p-3.5 rounded-xl border border-white/[0.06] font-sans">
              {analysis.summary}
            </p>
          </div>

          {/* Probable Root Cause */}
          <div>
            <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-rose-400">
              Probable Root Cause
            </span>
            <div className="text-sm text-rose-200/90 mt-1 bg-rose-950/20 border border-rose-500/20 p-3.5 rounded-xl leading-relaxed">
              {analysis.root_cause}
            </div>
          </div>

          {/* Technical Impact */}
          {(analysis.technical_impact || analysis.impact) && (
            <div>
              <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-cyan-400">
                Technical Impact
              </span>
              <div className="text-sm text-cyan-200/90 mt-1 bg-cyan-950/20 border border-cyan-500/20 p-3.5 rounded-xl leading-relaxed">
                {analysis.technical_impact || analysis.impact}
                {analysis.affected_assets && analysis.affected_assets.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {analysis.affected_assets.map((a: string) => (
                      <span key={a} className="text-[11px] px-2 py-1 rounded-full bg-white/5 border border-white/10 text-slate-300 font-mono">{a}</span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Business Impact */}
          {analysis.business_impact && (
            <div>
              <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-amber-400">
                Business Impact — What it means
              </span>
              <div className="text-sm text-amber-200/90 mt-1 bg-amber-950/20 border border-amber-500/20 p-3.5 rounded-xl leading-relaxed">
                {analysis.business_impact}
              </div>
            </div>
          )}

          {/* Recommended Remediation */}
          <div>
            <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-emerald-400">
              Recommended Operator Action
            </span>
            <div className="mt-1 p-4 rounded-xl bg-emerald-950/20 border border-emerald-500/25">
              <p className="text-sm font-semibold text-emerald-200">
                {analysis.recommended_action}
              </p>
              <p className="text-xs text-slate-400 mt-2 font-mono">
                Rule 4 Enforced: All AI recommendations require explicit human approval before touching downstream pipelines.
              </p>
            </div>
          </div>
        </div>

        {/* Action Bar with Nested Button-in-Button CTA Architecture */}
        {remediation && currentStatus === "PENDING" && (
          <div className="mt-7 pt-5 border-t border-white/[0.08] flex flex-col sm:flex-row items-center justify-between gap-4">
            <p className="text-xs text-slate-400">
              Your decision will be recorded with timestamp and operator ID in PostgreSQL.
            </p>
            <div className="flex items-center space-x-3 w-full sm:w-auto">
              <button
                onClick={() => handleAction(false)}
                disabled={loading}
                className="flex-1 sm:flex-none pl-4 pr-2 py-1.5 rounded-full text-xs font-semibold bg-white/5 hover:bg-rose-950/30 text-rose-300 border border-white/10 hover:border-rose-500/30 transition-all flex items-center justify-between sm:justify-start gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
              >
                <span>Reject</span>
                <span className="w-5 h-5 rounded-full bg-rose-500/20 flex items-center justify-center text-rose-400">
                  <X className="w-3 h-3 stroke-[2.5]" />
                </span>
              </button>

              <button
                onClick={() => handleAction(true)}
                disabled={loading}
                className="flex-1 sm:flex-none pl-5 pr-2 py-1.5 rounded-full text-xs font-bold bg-emerald-500 hover:bg-emerald-400 text-emerald-950 shadow-[0_0_20px_rgba(16,185,129,0.3)] transition-all flex items-center justify-between sm:justify-start gap-2.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
              >
                <span>Approve Remediation</span>
                <span className="w-5 h-5 rounded-full bg-emerald-950/25 flex items-center justify-center text-emerald-950">
                  <Check className="w-3 h-3 stroke-[3]" />
                </span>
              </button>
            </div>
          </div>
        )}

        {remediation && currentStatus !== "PENDING" && (
          <div className="mt-5 pt-4 border-t border-white/[0.08] text-xs text-slate-400 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
            <span>
              Decision Audit: <strong className={isApproved ? "text-emerald-400 font-mono" : "text-rose-400 font-mono"}>{currentStatus}</strong>
            </span>
            <span className="font-mono text-[11px] text-slate-500">
              Operator: {remediation.decision_by || "lead_engineer@dataguard.internal"}
            </span>
          </div>
        )}
      </div>
    </div>
  );
};
