"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Database, Table2, ShieldCheck, History, Network, AlertTriangle, Clock, Layers } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export default function DatasetDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [dataset, setDataset] = useState<any>(null);
  const [schema, setSchema] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [scans, setScans] = useState<any[]>([]);
  const [tab, setTab] = useState<"overview"|"schema"|"quality"|"history"|"lineage">("overview");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [dsRes, schRes, histRes, scansRes] = await Promise.all([
          fetch(`${API_BASE}/api/datasets/${id}`),
          fetch(`${API_BASE}/api/datasets/${id}/schema`),
          fetch(`${API_BASE}/api/datasets/${id}/history`),
          fetch(`${API_BASE}/api/datasets/${id}/scans`),
        ]);
        if (dsRes.ok) setDataset(await dsRes.json());
        if (schRes.ok) setSchema(await schRes.json());
        if (histRes.ok) {
          const h = await histRes.json();
          setHistory(h.history || []);
        }
        if (scansRes.ok) setScans(await scansRes.json());
      } finally { setLoading(false); }
    };
    if (id) load();
  }, [id]);

  if (loading) return <div className="py-20 text-center text-xs font-mono text-slate-400">Loading dataset…</div>;
  if (!dataset) return <div className="py-20 text-center text-slate-300">Dataset #{id} not found. <Link href="/datasets" className="text-emerald-400">Back</Link></div>;

  const latestScan = scans[0];
  const tabs = [
    { k: "overview", label: "Overview", icon: Database },
    { k: "schema", label: "Schema", icon: Table2 },
    { k: "quality", label: "Quality", icon: ShieldCheck },
    { k: "history", label: "History", icon: History },
    { k: "lineage", label: "Lineage", icon: Network },
  ] as const;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 pt-2">
        <Link href="/datasets" className="w-9 h-9 rounded-full bg-white/5 border border-white/10 flex items-center justify-center text-slate-400 hover:text-white"><ArrowLeft className="w-4 h-4" /></Link>
        <div>
          <h1 className="text-xl font-black text-white tracking-tight flex items-center gap-2">{dataset.name} <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-slate-400">{dataset.filename}</span></h1>
          <p className="text-xs text-slate-400 font-mono">{dataset.row_count} rows • {dataset.column_count} cols • created {new Date(dataset.created_at).toLocaleString()}</p>
        </div>
      </div>

      <div className="flex items-center gap-2 border-b border-white/10 pb-2 overflow-x-auto">
        {tabs.map(t => {
          const Icon = t.icon;
          const active = tab === t.k;
          return (
            <button key={t.k} onClick={()=>setTab(t.k as any)} className={`px-4 py-1.5 rounded-full text-xs font-semibold flex items-center gap-1.5 border transition ${active ? 'bg-white text-slate-900 border-white' : 'bg-white/5 text-slate-300 border-white/10 hover:bg-white/10'}`}>
              <Icon className="w-3.5 h-3.5" /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === "overview" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            <div className="rounded-[1.5rem] p-1 bg-white/[0.03] ring-1 ring-white/10">
              <div className="rounded-[calc(1.5rem-0.25rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6">
                <h3 className="text-sm font-bold text-white">Dataset Snapshot</h3>
                <div className="mt-3 grid grid-cols-3 gap-3 text-center">
                  <div className="rounded-xl bg-black/40 border border-white/10 p-4">
                    <div className="text-[10px] uppercase tracking-widest text-slate-400">Rows</div><div className="text-xl font-mono font-bold text-white mt-1">{dataset.row_count}</div>
                  </div>
                  <div className="rounded-xl bg-black/40 border border-white/10 p-4">
                    <div className="text-[10px] uppercase tracking-widest text-slate-400">Columns</div><div className="text-xl font-mono font-bold text-white mt-1">{dataset.column_count}</div>
                  </div>
                  <div className="rounded-xl bg-black/40 border border-white/10 p-4">
                    <div className="text-[10px] uppercase tracking-widest text-slate-400">Fingerprint</div><div className="text-[11px] font-mono text-cyan-300 mt-1 truncate">{schema?.fingerprint?.slice(0,12) || '—'}</div>
                  </div>
                </div>
                {latestScan && (
                  <div className="mt-4 p-3 rounded-xl bg-black/40 border border-white/10">
                    <div className="text-[11px] font-mono text-slate-400">Latest scan #{latestScan.id} • {latestScan.incident_severity || 'INFO'}</div>
                    <p className="text-xs text-slate-200 mt-1">{latestScan.incident_summary || 'No summary'}</p>
                    <Link href={`/scans/${latestScan.id}`} className="text-xs text-emerald-400 mt-2 inline-block">View scan →</Link>
                  </div>
                )}
              </div>
            </div>
          </div>
          <div className="rounded-[1.5rem] p-1 bg-white/[0.03] ring-1 ring-white/10">
            <div className="rounded-[calc(1.5rem-0.25rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6">
              <h3 className="text-sm font-bold text-white">Quick Stats</h3>
              <div className="mt-3 space-y-2 text-xs">
                <div className="flex justify-between"><span className="text-slate-400">Total scans</span><span className="text-white font-mono">{scans.length}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Critical scans</span><span className="text-rose-400 font-mono">{scans.filter((s:any)=>s.critical_count>0).length}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Last scan</span><span className="text-slate-300 font-mono">{latestScan ? new Date(latestScan.completed_at).toLocaleDateString() : '—'}</span></div>
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === "schema" && (
        <div className="rounded-[1.5rem] p-1 bg-white/[0.03] ring-1 ring-white/10">
          <div className="rounded-[calc(1.5rem-0.25rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 overflow-hidden">
            <div className="p-5 border-b border-white/10 flex items-center justify-between">
              <h3 className="text-sm font-bold text-white">Schema • {schema?.columns?.length || 0} columns</h3>
              <span className="text-[11px] font-mono px-2 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/20 text-cyan-300">{schema?.fingerprint?.slice(0,16)}</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-black/30 text-[10px] font-bold text-slate-400 uppercase tracking-widest border-b border-white/10">
                  <tr><th className="px-4 py-3">Column</th><th className="px-4 py-3">Type</th><th className="px-4 py-3">Null</th><th className="px-4 py-3">Unique</th><th className="px-4 py-3">Mean</th><th className="px-4 py-3">Top values</th></tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {(schema?.columns||[]).map((c:any)=>(
                    <tr key={c.id} className="hover:bg-white/[0.02]">
                      <td className="px-4 py-3 font-mono font-semibold text-white">{c.column_name}</td>
                      <td className="px-4 py-3"><span className="px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-slate-300 font-mono text-[11px]">{c.data_type}</span></td>
                      <td className="px-4 py-3 font-mono text-slate-300">{(c.null_rate*100).toFixed(1)}% ({c.null_count})</td>
                      <td className="px-4 py-3 font-mono text-slate-300">{c.unique_count} ({(c.unique_ratio*100).toFixed(0)}%)</td>
                      <td className="px-4 py-3 font-mono text-slate-300">{c.mean ?? '—'}</td>
                      <td className="px-4 py-3 text-slate-400">{(c.top_values||[]).map((t:any)=>`${t.value} (${t.count})`).join(', ') || (c.sample_values||[]).join(', ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {tab === "quality" && (
        <div className="rounded-[1.5rem] p-1 bg-white/[0.03] ring-1 ring-white/10">
          <div className="rounded-[calc(1.5rem-0.25rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6">
            <h3 className="text-sm font-bold text-white">Quality Overview</h3>
            <p className="text-xs text-slate-400 mt-1">Derived from last scan’s deterministic checks. See Scan detail for full issue list.</p>
            {latestScan ? (
              <div className="mt-4 grid grid-cols-3 gap-3 text-center">
                <div className="rounded-xl bg-emerald-500/10 border border-emerald-500/20 p-4"><div className="text-[10px] uppercase tracking-widest text-emerald-400">Healthy</div><div className="text-2xl font-mono font-bold text-white mt-1">{latestScan.healthy_count}</div></div>
                <div className="rounded-xl bg-amber-500/10 border border-amber-500/20 p-4"><div className="text-[10px] uppercase tracking-widest text-amber-400">Warning</div><div className="text-2xl font-mono font-bold text-white mt-1">{latestScan.warning_count}</div></div>
                <div className="rounded-xl bg-rose-500/10 border border-rose-500/20 p-4"><div className="text-[10px] uppercase tracking-widest text-rose-400">Critical</div><div className="text-2xl font-mono font-bold text-white mt-1">{latestScan.critical_count}</div></div>
              </div>
            ) : <div className="py-10 text-center text-xs text-slate-400">No scans yet.</div>}
            {latestScan && <Link href={`/scans/${latestScan.id}`} className="mt-4 inline-flex text-xs text-emerald-400">View issues →</Link>}
          </div>
        </div>
      )}

      {tab === "history" && (
        <div className="rounded-[1.5rem] p-1 bg-white/[0.03] ring-1 ring-white/10">
          <div className="rounded-[calc(1.5rem-0.25rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 overflow-hidden">
            <div className="p-5 border-b border-white/10"><h3 className="text-sm font-bold text-white">Scan History • {history.length} scans</h3></div>
            <div className="divide-y divide-white/5">
              {history.length===0 ? <div className="p-10 text-center text-xs text-slate-400">No history.</div> : history.slice().reverse().map((h:any)=>(
                <div key={h.scan_id} className="p-4 flex items-center justify-between hover:bg-white/[0.02]">
                  <div>
                    <div className="text-xs font-mono font-bold text-white">Scan #{h.scan_id} <span className={`ml-2 px-2 py-0.5 rounded-full text-[10px] border font-mono ${h.incident_severity==='CRITICAL'?'bg-rose-500/10 text-rose-300 border-rose-500/20':h.incident_severity==='WARNING'?'bg-amber-500/10 text-amber-300 border-amber-500/20':'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'}`}>{h.incident_severity}</span></div>
                    <div className="text-xs text-slate-300 mt-1 line-clamp-1">{h.incident_summary}</div>
                    <div className="text-[11px] font-mono text-slate-500 mt-1">{new Date(h.created_at).toLocaleString()} • {h.critical_count} crit • {h.warning_count} warn</div>
                  </div>
                  <Link href={`/scans/${h.scan_id}`} className="ml-4 px-3 py-1 rounded-full bg-white/5 border border-white/10 text-xs text-slate-300 hover:text-white">View</Link>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {tab === "lineage" && (
        <div className="rounded-[1.5rem] p-1 bg-white/[0.03] ring-1 ring-white/10">
          <div className="rounded-[calc(1.5rem-0.25rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6">
            <h3 className="text-sm font-bold text-white">Lineage • Demo</h3>
            <p className="text-xs text-slate-400 mt-1">Static lineage from <code className="text-cyan-300">lineage.py</code>. Replace with OpenLineage in production.</p>
            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
              {(schema?.columns||[]).slice(0,6).map((c:any)=>(
                <div key={c.id} className="p-3 rounded-xl bg-black/40 border border-white/10">
                  <div className="text-xs font-mono font-semibold text-white">{dataset.name}.{c.column_name}</div>
                  <div className="text-[11px] text-slate-400 mt-1">{c.data_type} • {c.null_count} nulls</div>
                  <Link href={`/scans/${latestScan?.id||''}`} className="text-[11px] text-cyan-400 mt-2 inline-block">Check impact →</Link>
                </div>
              ))}
            </div>
            <div className="mt-4 p-3 rounded-xl bg-amber-500/5 border border-amber-500/20 text-xs text-amber-200">
              This is demo lineage. For a real warehouse, connect dbt manifest or OpenLineage events.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
