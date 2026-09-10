"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, RefreshCw, AlertOctagon, CheckCircle2, ShieldAlert, Sparkles, Database } from "lucide-react";
import { SchemaDiff } from "@/components/SchemaDiff";
import { ImpactGraph } from "@/components/ImpactGraph";
import { AIRecommendation } from "@/components/AIRecommendation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export default function ScanDetailPage() {
  const params = useParams();
  const scanId = params.id;

  const [scan, setScan] = useState<any>(null);
  const [dataset, setDataset] = useState<any>(null);
  const [issues, setIssues] = useState<any[]>([]);
  const [lineageAssets, setLineageAssets] = useState<any[]>([]);
  const [activeColumn, setActiveColumn] = useState<string>("order_value");
  const [gate, setGate] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [analyzingAI, setAnalyzingAI] = useState(false);

  const fetchScanDetails = async () => {
    try {
      const scanRes = await fetch(`${API_BASE}/api/scans/${scanId}`);
      if (!scanRes.ok) throw new Error("Scan not found");
      const scanData = await scanRes.json();
      setScan(scanData);
      setIssues(scanData.issues || []);
      // fetch gate
      try {
        const gateRes = await fetch(`${API_BASE}/api/scans/${scanId}/gate`);
        if (gateRes.ok) setGate(await gateRes.json());
      } catch {}

      if (scanData.dataset_id) {
        const dsRes = await fetch(`${API_BASE}/api/datasets/${scanData.dataset_id}`);
        if (dsRes.ok) {
          const dsData = await dsRes.json();
          setDataset(dsData);

          const driftCol = scanData.issues.find((i: any) => i.column_name)?.column_name || "order_value";
          setActiveColumn(driftCol);

          const linRes = await fetch(`${API_BASE}/api/lineage/${dsData.name}/${driftCol}`);
          if (linRes.ok) {
            const linData = await linRes.json();
            setLineageAssets(linData.affected_assets || []);
          }
        }
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (scanId) {
      fetchScanDetails();
    }
  }, [scanId]);

  const handleTriggerAI = async () => {
    setAnalyzingAI(true);
    try {
      await fetch(`${API_BASE}/api/scans/${scanId}/analyze`, { method: "POST" });
      await fetchScanDetails();
    } finally {
      setAnalyzingAI(false);
    }
  };

  const handleRemediationDecision = async (remediationId: number, approved: boolean) => {
    const endpoint = approved ? "approve" : "reject";
    await fetch(`${API_BASE}/api/remediations/${remediationId}/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision_by: "lead_engineer@dataguard.ai",
        notes: approved ? "Approved schema compatibility mapping." : "Rejected - manual revision requested.",
      }),
    });
    await fetchScanDetails();
  };

  if (loading) {
    return (
      <div className="py-24 text-center text-xs font-mono text-slate-400">
        Loading scan telemetry & deterministic evaluation...
      </div>
    );
  }

  if (!scan) {
    return (
      <div className="py-24 text-center text-slate-300">
        <p className="text-base font-bold">Scan #{scanId} not found</p>
        <Link href="/" className="text-xs text-emerald-400 mt-2 inline-block">
          Return to Dashboard
        </Link>
      </div>
    );
  }

  const latestAI = scan.ai_analyses && scan.ai_analyses.length > 0 ? scan.ai_analyses[scan.ai_analyses.length - 1] : null;
  const latestRemediation = scan.remediations && scan.remediations.length > 0 ? scan.remediations[scan.remediations.length - 1] : null;

  return (
    <div className="space-y-8">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-2">
        <div className="flex items-center space-x-3.5">
          <Link
            href="/"
            className="w-9 h-9 rounded-full bg-white/5 border border-white/10 text-slate-400 hover:text-white hover:bg-white/10 flex items-center justify-center transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <div className="flex items-center space-x-2.5">
              <h1 className="text-xl sm:text-2xl font-black text-white tracking-tight">
                Scan Report #{scan.id}
              </h1>
              <span className="text-[10px] font-mono px-2.5 py-0.5 rounded-full bg-white/5 text-slate-300 border border-white/10">
                {dataset ? dataset.filename : `Dataset #${scan.dataset_id}`}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5 font-mono">
              Evaluated {new Date(scan.completed_at).toLocaleString()}
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-2.5">
          {!latestAI && (
            <button
              onClick={handleTriggerAI}
              disabled={analyzingAI}
              className="pl-4 pr-2 py-1.5 rounded-full bg-emerald-500 hover:bg-emerald-400 text-emerald-950 text-xs font-bold flex items-center gap-2 shadow-[0_0_20px_rgba(16,185,129,0.3)] transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
            >
              <span>{analyzingAI ? "Analyzing..." : "Analyze with AI"}</span>
              <span className="w-5 h-5 rounded-full bg-emerald-950/20 flex items-center justify-center text-emerald-950">
                <Sparkles className="w-3 h-3 stroke-[2.5]" />
              </span>
            </button>
          )}
          <button
            onClick={fetchScanDetails}
            className="w-9 h-9 rounded-full bg-white/5 border border-white/10 text-slate-400 hover:text-white flex items-center justify-center transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Summary KPI Triad */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* Critical */}
        <div className="rounded-[1.25rem] p-1 bg-white/[0.02] ring-1 ring-white/10">
          <div className="rounded-[calc(1.25rem-0.25rem)] bg-slate-900/90 p-5 flex items-center justify-between shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)]">
            <div>
              <span className="text-[10px] uppercase tracking-[0.2em] font-semibold text-rose-400">
                Critical Blockers
              </span>
              <h3 className="text-2xl font-extrabold text-white mt-1 font-mono">{scan.critical_count}</h3>
            </div>
            <div className="w-8 h-8 rounded-full bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400">
              <AlertOctagon className="w-4 h-4 stroke-[2.2]" />
            </div>
          </div>
        </div>

        {/* Warnings */}
        <div className="rounded-[1.25rem] p-1 bg-white/[0.02] ring-1 ring-white/10">
          <div className="rounded-[calc(1.25rem-0.25rem)] bg-slate-900/90 p-5 flex items-center justify-between shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)]">
            <div>
              <span className="text-[10px] uppercase tracking-[0.2em] font-semibold text-amber-400">
                Drift Warnings
              </span>
              <h3 className="text-2xl font-extrabold text-white mt-1 font-mono">{scan.warning_count}</h3>
            </div>
            <div className="w-8 h-8 rounded-full bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
              <ShieldAlert className="w-4 h-4 stroke-[2.2]" />
            </div>
          </div>
        </div>

        {/* Healthy */}
        <div className="rounded-[1.25rem] p-1 bg-white/[0.02] ring-1 ring-white/10">
          <div className="rounded-[calc(1.25rem-0.25rem)] bg-slate-900/90 p-5 flex items-center justify-between shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)]">
            <div>
              <span className="text-[10px] uppercase tracking-[0.2em] font-semibold text-emerald-400">
                Compliant Columns
              </span>
              <h3 className="text-2xl font-extrabold text-white mt-1 font-mono">{scan.healthy_count}</h3>
            </div>
            <div className="w-8 h-8 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <CheckCircle2 className="w-4 h-4 stroke-[2.2]" />
            </div>
          </div>
        </div>
      </div>

      {/* WHAT HAPPENED — Deterministic Incident Summary (human-friendly, not error code) */}
      {scan.incident_summary && (
        <div className={`rounded-[1.75rem] p-1.5 ring-1 shadow-[0_12px_40px_rgba(0,0,0,0.5)] ${scan.incident_severity === 'CRITICAL' ? 'bg-rose-500/10 ring-rose-500/20' : scan.incident_severity === 'WARNING' ? 'bg-amber-500/10 ring-amber-500/20' : 'bg-emerald-500/10 ring-emerald-500/20'}`}>
          <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6 shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)]">
            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${scan.incident_severity === 'CRITICAL' ? 'bg-rose-400' : scan.incident_severity === 'WARNING' ? 'bg-amber-400' : 'bg-emerald-400'}`} />
                  <span className={`text-[10px] font-bold uppercase tracking-[0.2em] ${scan.incident_severity === 'CRITICAL' ? 'text-rose-400' : scan.incident_severity === 'WARNING' ? 'text-amber-400' : 'text-emerald-400'}`}>What happened</span>
                  {gate && (
                    <span className={`ml-2 px-2 py-0.5 rounded-full text-[10px] font-mono font-bold border ${gate.passed ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20' : 'bg-rose-500/10 text-rose-300 border-rose-500/20'}`}>
                      GATE {gate.passed ? 'PASS' : 'FAIL'}
                    </span>
                  )}
                </div>
                <h3 className="text-sm font-bold text-white mt-2 leading-relaxed">{scan.incident_summary}</h3>
                {scan.incident_severity === 'CRITICAL' && activeColumn && dataset && (
                  <p className="text-xs text-rose-200/80 mt-2">
                    <span className="font-mono font-semibold text-rose-300">{dataset.name}.{activeColumn}</span> may be at risk — downstream models and KPIs could be affected. See Business Impact below.
                  </p>
                )}
              </div>
              <span className={`shrink-0 px-3 py-1 rounded-full text-xs font-bold border font-mono ${scan.incident_severity === 'CRITICAL' ? 'bg-rose-500/15 text-rose-300 border-rose-500/30' : scan.incident_severity === 'WARNING' ? 'bg-amber-500/15 text-amber-300 border-amber-500/30' : 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'}`}>
                {scan.incident_severity}
              </span>
            </div>
            {gate && !gate.passed && gate.reasons && gate.reasons.length > 0 && (
              <div className="mt-3 p-3 rounded-xl bg-black/40 border border-white/10 text-xs font-mono text-amber-300">
                <span className="font-bold">Gate failures:</span> {gate.reasons.join(' • ')}
              </div>
            )}
          </div>
        </div>
      )}

      {/* WHAT CHANGED — Deterministic Schema Diff (before AI) */}
      <SchemaDiff issues={issues} />

      {/* WHAT IS AFFECTED — Lineage Impact Graph */}
      {dataset && activeColumn && (
        <ImpactGraph
          columnName={activeColumn}
          datasetName={dataset.name}
          assets={lineageAssets}
        />
      )}

      {/* WHY + BUSINESS IMPACT + WHAT TO DO — AI Analyst */}
      {latestAI ? (
        <AIRecommendation
          analysis={latestAI}
          remediation={latestRemediation}
          onDecision={handleRemediationDecision}
        />
      ) : (
        <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10 shadow-[0_12px_40px_rgba(0,0,0,0.5)]">
          <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-8 text-center">
            <Sparkles className="w-8 h-8 text-teal-400 mx-auto mb-2 opacity-80" />
            <h3 className="text-sm font-bold text-white">AI Analysis Not Generated</h3>
            <p className="text-xs text-slate-400 mt-1 max-w-md mx-auto">
              Synthesize probable upstream root cause, trace downstream warehouse models, and generate human-in-the-loop remediation advice.
            </p>
            <button
              onClick={handleTriggerAI}
              disabled={analyzingAI}
              className="mt-4 pl-4 pr-2 py-1.5 rounded-full bg-emerald-500 hover:bg-emerald-400 text-emerald-950 text-xs font-bold inline-flex items-center gap-2 shadow-[0_0_20px_rgba(16,185,129,0.3)] transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
            >
              <span>{analyzingAI ? "Analyzing..." : "Run AI Analyst Agent"}</span>
              <span className="w-5 h-5 rounded-full bg-emerald-950/20 flex items-center justify-center text-emerald-950">
                <Sparkles className="w-3 h-3 stroke-[2.5]" />
              </span>
            </button>
          </div>
        </div>
      )}

      {/* Audit Trail — reconstructable timeline */}
      <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10 shadow-[0_12px_40px_rgba(0,0,0,0.5)]">
        <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6">
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Database className="w-4 h-4 text-slate-400" /> Audit Trail
          </h3>
          <p className="text-xs text-slate-400 mt-1">Reconstructable: scan → issues → AI → human decision.</p>
          <div className="mt-4 space-y-3">
            <div className="flex gap-3">
              <div className="w-7 h-7 rounded-full bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400 shrink-0"><span className="text-[10px] font-mono">1</span></div>
              <div>
                <div className="text-xs font-semibold text-white">Scan #{scan.id} executed</div>
                <div className="text-[11px] font-mono text-slate-400">{new Date(scan.completed_at).toLocaleString()} • {issues.length} issues • {scan.incident_severity}</div>
                <div className="text-xs text-slate-300 mt-1 line-clamp-2">{scan.incident_summary}</div>
              </div>
            </div>
            <div className="flex gap-3">
              <div className={`w-7 h-7 rounded-full border flex items-center justify-center shrink-0 ${latestAI ? 'bg-teal-500/10 border-teal-500/20 text-teal-400' : 'bg-white/5 border-white/10 text-slate-500'}`}><Sparkles className="w-3 h-3" /></div>
              <div>
                <div className="text-xs font-semibold text-white">AI analysis {latestAI ? `generated • ${latestAI.severity} • ${(latestAI.confidence*100).toFixed(0)}%` : "pending"}</div>
                {latestAI ? <div className="text-xs text-slate-300 mt-1 line-clamp-2">{latestAI.summary}</div> : <div className="text-[11px] text-slate-500">Click “Run AI Analyst” above.</div>}
              </div>
            </div>
            <div className="flex gap-3">
              <div className={`w-7 h-7 rounded-full border flex items-center justify-center shrink-0 ${latestRemediation?.status==='APPROVED'?'bg-emerald-500/10 border-emerald-500/20 text-emerald-400':latestRemediation?.status==='REJECTED'?'bg-rose-500/10 border-rose-500/20 text-rose-400':'bg-amber-500/10 border-amber-500/20 text-amber-400'}`}><ShieldAlert className="w-3 h-3" /></div>
              <div>
                <div className="text-xs font-semibold text-white">Human decision • {latestRemediation?.status || "PENDING"}</div>
                {latestRemediation ? (
                  <div className="text-[11px] font-mono text-slate-400 mt-1">{latestRemediation.decision_by || "—"} • {latestRemediation.decision_at ? new Date(latestRemediation.decision_at).toLocaleString() : "not yet decided"} {latestRemediation.notes ? `• ${latestRemediation.notes.slice(0,60)}` : ""}</div>
                ) : <div className="text-[11px] text-slate-500">Awaiting approval.</div>}
              </div>
            </div>
          </div>
          <div className="mt-4 text-[11px] font-mono text-slate-500">All decisions are persisted in PostgreSQL and visible at <Link href="/audit" className="text-cyan-400 hover:text-cyan-300">/audit</Link>.</div>
        </div>
      </div>
    </div>
  );
}
