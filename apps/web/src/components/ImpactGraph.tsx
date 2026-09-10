import React from "react";
import { ArrowRight, Database, LayoutDashboard, Cpu, Network } from "lucide-react";

interface AffectedAsset {
  name: string;
  asset_type: string;
  relationship: string;
}

interface ImpactGraphProps {
  columnName: string;
  datasetName: string;
  assets: AffectedAsset[];
}

export const ImpactGraph = ({ columnName, datasetName, assets }: ImpactGraphProps) => {
  const sqlModels = assets.filter(a => a.asset_type === "SQL_MODEL");
  const dashboards = assets.filter(a => a.asset_type === "DASHBOARD");

  return (
    <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10 shadow-[0_12px_40px_rgba(0,0,0,0.5)]">
      <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6 sm:p-7 shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)]">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-5 border-b border-white/[0.08]">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400">
              <Network className="w-4 h-4 stroke-[2.2]" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                Downstream Lineage Impact Graph
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Evaluates how structural changes to <span className="font-mono text-rose-300 font-semibold">{datasetName}.{columnName}</span> cascade downstream.
              </p>
            </div>
          </div>
          <span className="px-3 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-300 border border-rose-500/20 w-fit">
            {assets.length} Impacted Downstream Assets
          </span>
        </div>

        {/* 3-Tier Lineage Flow */}
        <div className="mt-6 grid grid-cols-1 md:grid-cols-7 gap-4 items-center">
          {/* 1. Source Ingestion Node */}
          <div className="md:col-span-2 rounded-2xl p-4 bg-black/40 border border-rose-500/30 text-center relative shadow-[0_0_24px_rgba(244,63,94,0.1)]">
            <span className="text-[10px] uppercase font-bold tracking-[0.2em] text-rose-400">
              Upstream Column
            </span>
            <div className="mt-2 text-xs font-mono font-bold text-white bg-slate-900 py-2.5 px-3 rounded-xl border border-rose-500/30">
              {datasetName}.<span className="text-rose-400">{columnName}</span>
            </div>
            <p className="text-[10px] text-slate-400 mt-2">Incoming Data Batch</p>
          </div>

          {/* Flow Connector 1 */}
          <div className="hidden md:flex md:col-span-1 justify-center">
            <div className="w-8 h-8 rounded-full bg-white/[0.03] border border-white/10 flex items-center justify-center text-slate-500">
              <ArrowRight className="w-4 h-4" />
            </div>
          </div>

          {/* 2. SQL Transformations */}
          <div className="md:col-span-2 rounded-2xl p-4 bg-black/40 border border-white/10">
            <div className="flex items-center space-x-2 mb-3">
              <Database className="w-3.5 h-3.5 text-cyan-400" />
              <span className="text-[10px] uppercase font-bold tracking-[0.2em] text-cyan-400">
                SQL / dbt Models
              </span>
            </div>
            <div className="space-y-2">
              {sqlModels.length > 0 ? (
                sqlModels.map((m, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between p-2.5 rounded-xl bg-slate-900/90 border border-white/[0.06] text-xs"
                  >
                    <span className="font-mono text-slate-200 font-medium">{m.name}</span>
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-300 font-mono">
                      {m.relationship}
                    </span>
                  </div>
                ))
              ) : (
                <p className="text-xs text-slate-500 italic py-2">No downstream SQL models mapped</p>
              )}
            </div>
          </div>

          {/* Flow Connector 2 */}
          <div className="hidden md:flex md:col-span-1 justify-center">
            <div className="w-8 h-8 rounded-full bg-white/[0.03] border border-white/10 flex items-center justify-center text-slate-500">
              <ArrowRight className="w-4 h-4" />
            </div>
          </div>

          {/* 3. BI Dashboards */}
          <div className="md:col-span-2 rounded-2xl p-4 bg-black/40 border border-white/10">
            <div className="flex items-center space-x-2 mb-3">
              <LayoutDashboard className="w-3.5 h-3.5 text-amber-400" />
              <span className="text-[10px] uppercase font-bold tracking-[0.2em] text-amber-400">
                Executive Dashboards
              </span>
            </div>
            <div className="space-y-2">
              {dashboards.length > 0 ? (
                dashboards.map((d, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between p-2.5 rounded-xl bg-slate-900/90 border border-white/[0.06] text-xs"
                  >
                    <span className="text-slate-200 font-medium">{d.name}</span>
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 font-mono font-semibold">
                      KPI
                    </span>
                  </div>
                ))
              ) : (
                <p className="text-xs text-slate-500 italic py-2">No executive dashboards affected</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
