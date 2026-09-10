import React from "react";
import { AlertOctagon, AlertTriangle, Info, CheckCircle, GitCompare, ShieldCheck } from "lucide-react";

interface IssueItem {
  id: number;
  issue_type: string;
  severity: string;
  column_name?: string;
  description: string;
  metadata?: any;
}

interface SchemaDiffProps {
  issues: IssueItem[];
}

export const SchemaDiff = ({ issues }: SchemaDiffProps) => {
  const schemaIssues = issues.filter(i =>
    ["COLUMN_REMOVED", "COLUMN_ADDED", "TYPE_CHANGED", "NULLABILITY_CHANGED"].includes(i.issue_type)
  );
  const qualityIssues = issues.filter(
    i => !["COLUMN_REMOVED", "COLUMN_ADDED", "TYPE_CHANGED", "NULLABILITY_CHANGED"].includes(i.issue_type)
  );

  const getSeverityBadge = (severity: string) => {
    switch (severity) {
      case "CRITICAL":
        return (
          <span className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-rose-500/15 text-rose-300 border border-rose-500/30 flex items-center gap-1 font-mono">
            <AlertOctagon className="w-3 h-3" /> CRITICAL
          </span>
        );
      case "WARNING":
        return (
          <span className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30 flex items-center gap-1 font-mono">
            <AlertTriangle className="w-3 h-3" /> WARNING
          </span>
        );
      default:
        return (
          <span className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 flex items-center gap-1 font-mono">
            <Info className="w-3 h-3" /> INFO
          </span>
        );
    }
  };

  const getPrefixIcon = (issueType: string) => {
    if (issueType === "COLUMN_REMOVED") {
      return <span className="text-rose-400 font-mono font-bold text-sm select-none">−</span>;
    }
    if (issueType === "COLUMN_ADDED") {
      return <span className="text-emerald-400 font-mono font-bold text-sm select-none">+</span>;
    }
    return <span className="text-amber-400 font-mono font-bold text-sm select-none">~</span>;
  };

  return (
    <div className="space-y-6">
      {/* 1. Deterministic Schema Drift Section */}
      <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10 shadow-[0_12px_40px_rgba(0,0,0,0.5)]">
        <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6 sm:p-7 shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)]">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div className="flex items-center space-x-3">
              <div className="w-8 h-8 rounded-full bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
                <GitCompare className="w-4 h-4 stroke-[2.2]" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white tracking-tight">
                  Deterministic Schema Drift Inspection
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Structural deviations evaluated strictly against baseline contracts
                </p>
              </div>
            </div>
            <span className="text-xs font-mono text-slate-400">
              {schemaIssues.length} Structural Changes
            </span>
          </div>

          {schemaIssues.length === 0 ? (
            <div className="py-10 text-center text-slate-400 flex flex-col items-center">
              <div className="w-10 h-10 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-2">
                <CheckCircle className="w-5 h-5" />
              </div>
              <p className="text-sm font-semibold text-white">Schema strictly identical to baseline</p>
              <p className="text-xs text-slate-400 mt-1">Zero column additions, removals, or datatype mutations.</p>
            </div>
          ) : (
            <div className="mt-4 divide-y divide-white/[0.06]">
              {schemaIssues.map(issue => (
                <div key={issue.id} className="py-3.5 flex items-start justify-between gap-4">
                  <div className="flex items-start space-x-3">
                    <div className="w-6 h-6 rounded-md bg-slate-900 border border-white/10 flex items-center justify-center mt-0.5">
                      {getPrefixIcon(issue.issue_type)}
                    </div>
                    <div className="space-y-1">
                      <div className="flex items-center space-x-2">
                        <span className="font-mono text-xs font-bold text-slate-100">
                          {issue.column_name || "Root"}
                        </span>
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-white/5 text-slate-300 border border-white/10">
                          {issue.issue_type}
                        </span>
                      </div>
                      <p className="text-xs text-slate-300">{issue.description}</p>
                    </div>
                  </div>
                  <div className="shrink-0">{getSeverityBadge(issue.severity)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 2. Deterministic Data Quality Findings */}
      <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10 shadow-[0_12px_40px_rgba(0,0,0,0.5)]">
        <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6 sm:p-7 shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)]">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div className="flex items-center space-x-3">
              <div className="w-8 h-8 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
                <ShieldCheck className="w-4 h-4 stroke-[2.2]" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white tracking-tight">
                  Deterministic Data Quality Guardrails
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Primary key uniqueness, null bounds, date syntax, and numeric boundaries
                </p>
              </div>
            </div>
            <span className="text-xs font-mono text-slate-400">
              {qualityIssues.length} Findings
            </span>
          </div>

          {qualityIssues.length === 0 ? (
            <div className="py-10 text-center text-slate-400 flex flex-col items-center">
              <div className="w-10 h-10 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-2">
                <CheckCircle className="w-5 h-5" />
              </div>
              <p className="text-sm font-semibold text-white">All quality bounds respected</p>
              <p className="text-xs text-slate-400 mt-1">Primary keys are unique and non-null; no range violations.</p>
            </div>
          ) : (
            <div className="mt-4 divide-y divide-white/[0.06]">
              {qualityIssues.map(issue => (
                <div key={issue.id} className="py-3.5 flex items-start justify-between gap-4">
                  <div className="space-y-1">
                    <div className="flex items-center space-x-2">
                      <span className="font-mono text-xs font-bold text-slate-100">
                        {issue.column_name || "Dataset"}
                      </span>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-white/5 text-slate-300 border border-white/10">
                        {issue.issue_type}
                      </span>
                    </div>
                    <p className="text-xs text-slate-300">{issue.description}</p>
                  </div>
                  <div className="shrink-0">{getSeverityBadge(issue.severity)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
