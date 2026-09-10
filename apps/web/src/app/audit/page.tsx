"use client";
import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Clock, ShieldCheck, CheckCircle2, XCircle, AlertTriangle, ArrowLeft } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export default function AuditPage() {
  const [trail, setTrail] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<string>("all");
  const [severity, setSeverity] = useState<string>("all");
  const [datasets, setDatasets] = useState<any[]>([]);
  const [datasetId, setDatasetId] = useState<string>("all");
  const fetchTrail = async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (status !== "all") params.set("status", status);
    if (severity !== "all") params.set("severity", severity);
    if (datasetId !== "all") params.set("dataset_id", datasetId);
    params.set("limit", "50");
    const res = await fetch(`${API_BASE}/api/audit?${params.toString()}`);
    if (res.ok) setTrail(await res.json());
    setLoading(false);
  };
  useEffect(() => { fetchTrail(); }, [status, severity, datasetId]);
  useEffect(() => {
    fetch(`${API_BASE}/api/datasets`).then(r=>r.json()).then(setDatasets).catch(()=>{});
  }, []);
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 pt-2">
        <Link href="/" className="w-9 h-9 rounded-full bg-white/5 border border-white/10 flex items-center justify-center text-slate-400 hover:text-white"><ArrowLeft className="w-4 h-4" /></Link>
        <div>
          <h1 className="text-xl font-black text-white tracking-tight">Audit Trail</h1>
          <p className="text-xs text-slate-400">Every scan → issue → AI analysis → human decision, reconstructable.</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select value={status} onChange={e=>setStatus(e.target.value)} className="px-3 py-1.5 rounded-full bg-black/40 border border-white/10 text-xs text-white">
          <option value="all">All status</option><option value="PENDING">PENDING</option><option value="APPROVED">APPROVED</option><option value="REJECTED">REJECTED</option>
        </select>
        <select value={severity} onChange={e=>setSeverity(e.target.value)} className="px-3 py-1.5 rounded-full bg-black/40 border border-white/10 text-xs text-white">
          <option value="all">All severity</option><option value="CRITICAL">CRITICAL</option><option value="WARNING">WARNING</option><option value="INFO">INFO</option>
        </select>
        <select value={datasetId} onChange={e=>setDatasetId(e.target.value)} className="px-3 py-1.5 rounded-full bg-black/40 border border-white/10 text-xs text-white max-w-[160px]">
          <option value="all">All datasets</option>{datasets.map((d:any)=><option key={d.id} value={d.id}>{d.name} #{d.id}</option>)}
        </select>
        <span className="text-[11px] font-mono text-slate-500 ml-auto">{trail.length} records</span>
      </div>
      {loading ? <div className="py-20 text-center text-xs font-mono text-slate-400">Loading audit…</div> : trail.length===0 ? <div className="py-20 text-center text-slate-400 text-sm">No decisions yet. Run a scan and approve a remediation.</div> : (
        <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10">
          <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 overflow-hidden">
            <div className="p-5 border-b border-white/10 flex items-center justify-between">
              <h3 className="text-sm font-bold text-white">Decision History • {trail.length}</h3>
              <span className="text-xs font-mono text-slate-400">{new Date().toLocaleDateString()}</span>
            </div>
            <div className="divide-y divide-white/5">
              {trail.map(t=>(
                <div key={t.remediation_id} className="p-4 flex items-start justify-between gap-4 hover:bg-white/[0.02]">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border font-mono ${t.incident_severity==='CRITICAL'?'bg-rose-500/10 text-rose-300 border-rose-500/20':t.incident_severity==='WARNING'?'bg-amber-500/10 text-amber-300 border-amber-500/20':'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'}`}>{t.incident_severity}</span>
                      <span className="text-xs font-mono font-semibold text-white">Scan #{t.scan_id} • {t.dataset_name}</span>
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border font-mono ${t.status==='APPROVED'?'bg-emerald-500/10 text-emerald-300 border-emerald-500/20':t.status==='REJECTED'?'bg-rose-500/10 text-rose-300 border-rose-500/20':'bg-amber-500/10 text-amber-300 border-amber-500/20'}`}>{t.status}</span>
                    </div>
                    <p className="text-xs text-slate-300 mt-1 line-clamp-2">{t.incident_summary}</p>
                    {t.business_impact && <p className="text-[11px] text-amber-300/70 mt-1 line-clamp-1">↳ {t.business_impact}</p>}
                    <p className="text-[11px] text-slate-400 mt-1">{t.suggestion.slice(0,120)}</p>
                    <div className="text-[11px] font-mono text-slate-500 mt-1 flex items-center gap-3">
                      <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> {t.decision_at ? new Date(t.decision_at).toLocaleString() : (t.scan_completed_at ? new Date(t.scan_completed_at).toLocaleString() : 'pending')}</span>
                      {t.decision_by && <span>{t.decision_by}</span>}
                    </div>
                  </div>
                  <Link href={`/scans/${t.scan_id}`} className="shrink-0 px-3 py-1 rounded-full bg-white/5 border border-white/10 text-xs text-slate-300 hover:text-white">View</Link>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
