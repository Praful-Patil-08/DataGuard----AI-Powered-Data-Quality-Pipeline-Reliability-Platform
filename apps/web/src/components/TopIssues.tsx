import React from "react";
import Link from "next/link";
import { AlertTriangle, XCircle, ArrowRight, Flame } from "lucide-react";

interface TopIssue {
  scan_id: number;
  dataset_id: number;
  dataset_name: string;
  filename: string;
  severity: string;
  issue_type: string;
  column_name?: string | null;
  description: string;
  created_at: string;
}

interface Props {
  issues: TopIssue[];
  loading?: boolean;
}

export const TopIssues = ({ issues, loading }: Props) => {
  return (
    <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10 shadow-[0_12px_40px_rgba(0,0,0,0.5)]">
      <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6 sm:p-7 shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)]">
        <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
              <Flame className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white tracking-tight">Top Active Issues</h3>
              <p className="text-xs text-slate-400 mt-0.5">Most recent critical & warning drifts requiring attention</p>
            </div>
          </div>
          <span className="text-xs font-mono text-slate-400">{issues.length} active</span>
        </div>

        {loading ? (
          <div className="py-10 text-center text-xs font-mono text-slate-400">Loading issues…</div>
        ) : issues.length === 0 ? (
          <div className="py-10 text-center">
            <div className="w-10 h-10 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mx-auto">
              <span className="text-lg">✓</span>
            </div>
            <p className="text-sm font-semibold text-white mt-3">No active issues</p>
            <p className="text-xs text-slate-400 mt-1">All datasets healthy. Keep monitoring.</p>
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {issues.map((iss) => (
              <Link
                key={`${iss.scan_id}-${iss.issue_type}-${iss.column_name}`}
                href={`/scans/${iss.scan_id}`}
                className="flex items-center justify-between p-4 rounded-2xl bg-black/40 border border-white/[0.06] hover:border-white/10 hover:bg-black/50 transition-all group"
              >
                <div className="flex items-start gap-3 min-w-0">
                  <div className={`mt-0.5 w-7 h-7 rounded-full flex items-center justify-center border shrink-0 ${iss.severity === 'CRITICAL' ? 'bg-rose-500/10 border-rose-500/20 text-rose-400' : 'bg-amber-500/10 border-amber-500/20 text-amber-400'}`}>
                    {iss.severity === 'CRITICAL' ? <XCircle className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border font-mono ${iss.severity === 'CRITICAL' ? 'bg-rose-500/10 text-rose-300 border-rose-500/20' : 'bg-amber-500/10 text-amber-300 border-amber-500/20'}`}>{iss.severity}</span>
                      <span className="text-xs font-mono font-semibold text-white truncate">{iss.dataset_name}</span>
                      <span className="text-[11px] px-1.5 py-0.5 rounded bg-white/5 border border-white/10 text-slate-300 font-mono">{iss.issue_type}</span>
                    </div>
                    <p className="text-xs text-slate-300 mt-1 line-clamp-1">{iss.description}</p>
                    <p className="text-[11px] text-slate-500 font-mono mt-1">{iss.column_name || 'dataset'} • {new Date(iss.created_at).toLocaleDateString()}</p>
                  </div>
                </div>
                <div className="ml-3 w-7 h-7 rounded-full bg-white/5 border border-white/10 flex items-center justify-center text-slate-400 group-hover:text-white group-hover:bg-white/10 transition shrink-0">
                  <ArrowRight className="w-3 h-3" />
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
