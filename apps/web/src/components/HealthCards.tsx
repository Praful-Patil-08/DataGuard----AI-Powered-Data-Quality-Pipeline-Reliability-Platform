import React from "react";
import { CheckCircle2, AlertTriangle, XCircle, Layers } from "lucide-react";

interface HealthStatsProps {
  stats: {
    datasets_count: number;
    total_scans: number;
    healthy_count: number;
    warning_count: number;
    critical_count: number;
    pending_remediations: number;
  };
}

export const HealthCards = ({ stats }: HealthStatsProps) => {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* 1. Healthy Scans */}
      <div className="rounded-[1.25rem] p-1 bg-white/[0.02] ring-1 ring-white/10 shadow-[0_4px_20px_rgba(0,0,0,0.3)] transition-all duration-300 hover:ring-emerald-500/30 group">
        <div className="rounded-[calc(1.25rem-0.25rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)] h-full flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.2em] font-semibold text-emerald-400">
              Passing Pipelines
            </span>
            <div className="w-8 h-8 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <CheckCircle2 className="w-4 h-4 stroke-[2.2]" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-3xl font-extrabold text-white tracking-tight font-mono">
              {stats.healthy_count}
            </div>
            <p className="text-[11px] text-slate-400 mt-1">
              Deterministic schema & quality guarantees met
            </p>
          </div>
        </div>
      </div>

      {/* 2. Warnings */}
      <div className="rounded-[1.25rem] p-1 bg-white/[0.02] ring-1 ring-white/10 shadow-[0_4px_20px_rgba(0,0,0,0.3)] transition-all duration-300 hover:ring-amber-500/30 group">
        <div className="rounded-[calc(1.25rem-0.25rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)] h-full flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.2em] font-semibold text-amber-400">
              Drift Warnings
            </span>
            <div className="w-8 h-8 rounded-full bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
              <AlertTriangle className="w-4 h-4 stroke-[2.2]" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-3xl font-extrabold text-white tracking-tight font-mono">
              {stats.warning_count}
            </div>
            <p className="text-[11px] text-slate-400 mt-1">
              Non-breaking column additions or variance
            </p>
          </div>
        </div>
      </div>

      {/* 3. Critical Blockers */}
      <div className="rounded-[1.25rem] p-1 bg-white/[0.02] ring-1 ring-white/10 shadow-[0_4px_20px_rgba(0,0,0,0.3)] transition-all duration-300 hover:ring-rose-500/30 group">
        <div className="rounded-[calc(1.25rem-0.25rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)] h-full flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.2em] font-semibold text-rose-400">
              Critical Blockers
            </span>
            <div className="w-8 h-8 rounded-full bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400">
              <XCircle className="w-4 h-4 stroke-[2.2]" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-3xl font-extrabold text-white tracking-tight font-mono">
              {stats.critical_count}
            </div>
            <p className="text-[11px] text-slate-400 mt-1">
              Pipeline halted to prevent downstream BI corruption
            </p>
          </div>
        </div>
      </div>

      {/* 4. Total Datasets & Reviews */}
      <div className="rounded-[1.25rem] p-1 bg-white/[0.02] ring-1 ring-white/10 shadow-[0_4px_20px_rgba(0,0,0,0.3)] transition-all duration-300 hover:ring-cyan-500/30 group">
        <div className="rounded-[calc(1.25rem-0.25rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)] h-full flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.2em] font-semibold text-cyan-400">
              Audit Queue
            </span>
            <div className="w-8 h-8 rounded-full bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
              <Layers className="w-4 h-4 stroke-[2.2]" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-3xl font-extrabold text-white tracking-tight font-mono">
              {stats.pending_remediations}
            </div>
            <p className="text-[11px] text-slate-400 mt-1">
              Across {stats.datasets_count} monitored datasets & {stats.total_scans} scans
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
