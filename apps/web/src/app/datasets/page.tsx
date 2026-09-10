"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { Database, Clock, Layers, CheckCircle2, AlertTriangle, XCircle, ArrowRight, Search } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export default function DatasetsPage() {
  const [datasets, setDatasets] = useState<any[]>([]);
  const [scansMap, setScansMap] = useState<Record<number, any>>({});
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/datasets`);
        if (res.ok) {
          const ds = await res.json();
          setDatasets(ds);
          // fetch latest scan per dataset via history
          const map: Record<number, any> = {};
          await Promise.all(ds.map(async (d: any) => {
            try {
              const h = await window.fetch(`${API_BASE}/api/datasets/${d.id}/history`);
              if (h.ok) {
                const hj = await h.json();
                if (hj.history && hj.history.length > 0) {
                  map[d.id] = hj.history[hj.history.length - 1]; // last is newest (asc order)
                }
              }
            } catch {}
          }));
          setScansMap(map);
        }
      } finally { setLoading(false); }
    };
    load();
  }, []);

  const filtered = datasets.filter(d => d.name.toLowerCase().includes(filter.toLowerCase()) || d.filename.toLowerCase().includes(filter.toLowerCase()));

  const getStatus = (scan: any) => {
    if (!scan) return { label: "NO SCAN", color: "text-slate-400", bg: "bg-white/5", border: "border-white/10", icon: Layers };
    if (scan.critical_count > 0 || scan.incident_severity === "CRITICAL") return { label: "CRITICAL", color: "text-rose-400", bg: "bg-rose-500/10", border: "border-rose-500/20", icon: XCircle };
    if (scan.warning_count > 0 || scan.incident_severity === "WARNING") return { label: "WARNING", color: "text-amber-400", bg: "bg-amber-500/10", border: "border-amber-500/20", icon: AlertTriangle };
    return { label: "HEALTHY", color: "text-emerald-400", bg: "bg-emerald-500/10", border: "border-emerald-500/20", icon: CheckCircle2 };
  };

  return (
    <div className="space-y-8">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 pt-2">
        <div>
          <h1 className="text-2xl sm:text-3xl font-black text-white tracking-tight">Datasets</h1>
          <p className="text-xs text-slate-400 mt-1 max-w-xl">Managed datasets with profiling, lineage and scan history. Click a dataset to inspect schema, quality and lineage.</p>
        </div>
        <div className="relative w-full sm:w-72">
          <Search className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input value={filter} onChange={e=>setFilter(e.target.value)} placeholder="Search datasets..." className="w-full pl-9 pr-3 py-2 rounded-full bg-white/[0.04] border border-white/10 text-xs text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-400" />
        </div>
      </div>

      {loading ? (
        <div className="py-20 text-center text-xs font-mono text-slate-400">Loading datasets…</div>
      ) : filtered.length === 0 ? (
        <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10">
          <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-12 text-center">
            <Database className="w-8 h-8 text-slate-500 mx-auto mb-3" />
            <p className="text-sm font-semibold text-white">No datasets</p>
            <p className="text-xs text-slate-400 mt-1">Upload a CSV or run a demo from the Overview.</p>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filtered.map(ds => {
            const scan = scansMap[ds.id];
            const st = getStatus(scan);
            const Icon = st.icon;
            return (
              <Link key={ds.id} href={`/datasets/${ds.id}`} className="group rounded-[1.5rem] p-1 bg-white/[0.03] ring-1 ring-white/10 hover:ring-white/20 transition">
                <div className="rounded-[calc(1.5rem-0.25rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-5">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`w-9 h-9 rounded-xl flex items-center justify-center border ${st.bg} ${st.border} ${st.color}`}>
                        <Database className="w-4 h-4" />
                      </div>
                      <div>
                        <div className="text-sm font-bold text-white tracking-tight">{ds.name}</div>
                        <div className="text-[11px] font-mono text-slate-400">{ds.filename} • {ds.row_count} rows • {ds.column_count} cols</div>
                      </div>
                    </div>
                    <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold border font-mono flex items-center gap-1 ${st.bg} ${st.color} ${st.border}`}>
                      <Icon className="w-3 h-3" /> {st.label}
                    </span>
                  </div>
                  <div className="mt-4 flex items-center justify-between text-[11px] font-mono text-slate-500">
                    <span className="flex items-center gap-1.5"><Clock className="w-3 h-3" /> {scan ? new Date(scan.created_at).toLocaleString() : "never scanned"}</span>
                    <span className="flex items-center gap-1 text-slate-300 group-hover:text-white">Inspect <ArrowRight className="w-3 h-3" /></span>
                  </div>
                  {scan && scan.incident_summary && (
                    <p className="mt-3 text-xs text-slate-300 line-clamp-2 bg-black/30 p-2.5 rounded-xl border border-white/[0.06]">{scan.incident_summary}</p>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
