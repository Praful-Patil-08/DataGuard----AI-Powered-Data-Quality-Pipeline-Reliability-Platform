import React from "react";
import { ShieldCheck, ShieldAlert, AlertOctagon, LayoutDashboard } from "lucide-react";

interface ImpactItem {
  kpi: string;
  status: string;
  affected_datasets: string[];
  affected_columns: string[];
  description: string;
}

interface Props {
  items: ImpactItem[];
  loading?: boolean;
}

const statusMap: Record<string, { label: string; color: string; bg: string; border: string; icon: any }> = {
  HEALTHY: { label: "HEALTHY", color: "text-emerald-400", bg: "bg-emerald-500/10", border: "border-emerald-500/20", icon: ShieldCheck },
  "AT RISK": { label: "AT RISK", color: "text-amber-400", bg: "bg-amber-500/10", border: "border-amber-500/20", icon: ShieldAlert },
  CRITICAL: { label: "AT RISK", color: "text-rose-400", bg: "bg-rose-500/10", border: "border-rose-500/20", icon: AlertOctagon },
};

export const BusinessImpact = ({ items, loading }: Props) => {
  return (
    <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10 shadow-[0_12px_40px_rgba(0,0,0,0.5)]">
      <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6 sm:p-7 shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)]">
        <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded-xl bg-teal-500/10 border border-teal-500/20 flex items-center justify-center text-teal-400">
              <LayoutDashboard className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white tracking-tight">Business Impact</h3>
              <p className="text-xs text-slate-400 mt-0.5">KPI & dashboard health derived from deterministic findings</p>
            </div>
          </div>
          <span className="text-xs font-mono text-slate-400">{items.filter(i=>i.status!=='HEALTHY').length} at risk</span>
        </div>

        {loading ? (
          <div className="py-10 text-center text-xs font-mono text-slate-400">Loading business impact…</div>
        ) : (
          <div className="mt-5 grid grid-cols-1 md:grid-cols-2 gap-4">
            {items.map((it) => {
              const cfg = statusMap[it.status] || statusMap.HEALTHY;
              const Icon = cfg.icon;
              return (
                <div key={it.kpi} className={`rounded-2xl p-4 border bg-black/40 flex flex-col justify-between ${cfg.border}`}>
                  <div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-white tracking-tight">{it.kpi}</span>
                      <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold border font-mono flex items-center gap-1.5 ${cfg.bg} ${cfg.color} ${cfg.border}`}>
                        <Icon className="w-3 h-3" /> {cfg.label}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-1.5">{it.description}</p>
                    {it.affected_datasets.length > 0 ? (
                      <div className="mt-3">
                        <div className="text-[10px] font-mono uppercase tracking-widest text-slate-500">Affected</div>
                        <div className="mt-1 flex flex-wrap gap-1.5">
                          {it.affected_columns.slice(0,3).map(c => (
                            <span key={c} className="text-[11px] px-2 py-1 rounded-full bg-white/5 border border-white/10 text-slate-300 font-mono">{c}</span>
                          ))}
                          {it.affected_datasets.map(d => (
                            <span key={d} className="text-[11px] px-2 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/20 text-cyan-300 font-mono">{d}</span>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <div className="mt-3 text-[11px] text-emerald-300/80 font-mono">No active drift on upstream columns</div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <p className="text-[11px] text-slate-500 mt-4 font-mono">Demo lineage • configured in <span className="text-slate-300">lineage.py</span> • replace with OpenLineage/dbt in production.</p>
      </div>
    </div>
  );
};
