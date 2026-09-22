"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { Upload, FileUp, Activity, CheckCircle, AlertTriangle, XCircle, ArrowRight, RefreshCw, Sparkles, Play, Shield } from "lucide-react";
import { HealthCards } from "@/components/HealthCards";
import { ReliabilityTrend } from "@/components/ReliabilityTrend";
import { TopIssues } from "@/components/TopIssues";
import { BusinessImpact } from "@/components/BusinessImpact";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export default function Dashboard() {
  const [stats, setStats] = useState({
    datasets_count: 0,
    total_scans: 0,
    healthy_count: 0,
    warning_count: 0,
    critical_count: 0,
    pending_remediations: 0,
  });

  const [scans, setScans] = useState<any[]>([]);
  const [trend, setTrend] = useState<any[]>([]);
  const [topIssues, setTopIssues] = useState<any[]>([]);
  const [businessImpact, setBusinessImpact] = useState<any[]>([]);
  const [incidents, setIncidents] = useState<any[]>([]);
  const [reliability, setReliability] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [dashLoading, setDashLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);

  const fetchDashboardData = async () => {
    try {
      const [statsRes, scansRes, trendRes, topRes, impactRes] = await Promise.all([
        fetch(`${API_BASE}/api/dashboard/stats`),
        fetch(`${API_BASE}/api/scans`),
        fetch(`${API_BASE}/api/dashboard/reliability-trend?days=30`),
        fetch(`${API_BASE}/api/dashboard/top-issues?limit=5`),
        fetch(`${API_BASE}/api/dashboard/business-impact`),
        fetch(`${API_BASE}/api/incidents?status=OPEN&limit=5`),
        fetch(`${API_BASE}/api/reliability/overview`),
      ]);

      if (statsRes.ok) {
        const statsData = await statsRes.json();
        setStats(statsData);
      }
      if (scansRes.ok) {
        const scansData = await scansRes.json();
        setScans(scansData);
      }
      if (trendRes.ok) setTrend(await trendRes.json());
      if (topRes.ok) setTopIssues(await topRes.json());
      if (impactRes.ok) setBusinessImpact(await impactRes.json());
      // incidents and reliability (incident-first)
      try { const r = await fetch(`${API_BASE}/api/incidents?status=OPEN&limit=5`); if (r.ok) setIncidents(await r.json()); } catch {}
      try { const r = await fetch(`${API_BASE}/api/reliability/overview`); if (r.ok) setReliability(await r.json()); } catch {}
    } catch (err) {
      console.error("Error fetching dashboard data", err);
    } finally {
      setLoading(false);
      setDashLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    const file = e.target.files[0];
    setUploading(true);
    setUploadMessage("Uploading & executing deterministic schema profiling...");

    try {
      const formData = new FormData();
      formData.append("file", file);

      // 1. Upload dataset
      const uploadRes = await fetch(`${API_BASE}/api/datasets/upload`, {
        method: "POST",
        body: formData,
      });

      if (!uploadRes.ok) {
        const err = await uploadRes.json();
        throw new Error(err.detail || "Upload failed");
      }

      const uploadData = await uploadRes.json();

      // 2. Trigger automated scan
      setUploadMessage("Running deterministic drift & quality engines...");
      const scanRes = await fetch(`${API_BASE}/api/datasets/${uploadData.dataset_id}/scan`, {
        method: "POST",
      });

      if (scanRes.ok) {
        const scanData = await scanRes.json();
        // 3. Automatically trigger AI analyst
        setUploadMessage("Generating AI root-cause diagnosis & downstream impact...");
        await fetch(`${API_BASE}/api/scans/${scanData.id}/analyze`, { method: "POST" });
      }

      setUploadMessage("Dataset successfully profiled and diagnosed!");
      await fetchDashboardData();
    } catch (err: any) {
      setUploadMessage(`Error: ${err.message}`);
    } finally {
      setUploading(false);
      setTimeout(() => setUploadMessage(null), 4000);
    }
  };

  const handleSeedDemo = async (sampleName: string) => {
    setUploading(true);
    setUploadMessage(`Triggering ${sampleName} through automated reliability engine...`);
    try {
      const res = await fetch(`${API_BASE}/api/demo/seed/${sampleName}`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Demo execution failed");
      }
      setUploadMessage(`Sample ${sampleName} successfully executed and diagnosed!`);
      await fetchDashboardData();
    } catch (err: any) {
      setUploadMessage(`Error: ${err.message}`);
    } finally {
      setUploading(false);
      setTimeout(() => setUploadMessage(null), 4000);
    }
  };

  return (
    <div className="space-y-10">
      {/* Hero & Eyebrow */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-2">
        <div className="space-y-2">
          <div className="flex items-center space-x-2">
            <span className="rounded-full px-3 py-1 text-[10px] uppercase tracking-[0.2em] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              Data Pipeline Observability
            </span>
            <span className="text-xs text-slate-500 font-mono">Zero-Hallucination Engine</span>
          </div>
          <h1 className="text-2xl sm:text-3xl lg:text-4xl font-black text-white tracking-tight">
            Pipeline Health & Schema Drift
          </h1>
          <p className="text-xs sm:text-sm text-slate-400 max-w-2xl leading-relaxed">
            Deterministic validation for data pipelines with AI-powered root-cause reasoning and human-approved remediations.
          </p>
        </div>

        <button
          onClick={fetchDashboardData}
          className="flex items-center space-x-2 pl-3.5 pr-2 py-1.5 rounded-full text-xs font-semibold bg-white/5 border border-white/10 text-slate-300 hover:text-white hover:bg-white/10 transition-all w-fit shadow-lg shadow-black/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
        >
          <span>Refresh Telemetry</span>
          <span className="w-5 h-5 rounded-full bg-white/10 flex items-center justify-center text-slate-300">
            <RefreshCw className="w-3 h-3" />
          </span>
        </button>
      </div>

      {/* Metrics Double-Bezel Cards */}
      <HealthCards stats={stats} />

      {/* Incident-First — What is broken? */}
      {incidents.length > 0 && (
        <div className="rounded-[1.75rem] p-1.5 bg-rose-500/5 ring-1 ring-rose-500/20 shadow-[0_12px_40px_rgba(0,0,0,0.5)]">
          <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6 shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)]">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-bold text-white flex items-center gap-2"><XCircle className="w-4 h-4 text-rose-400" /> What is broken? — Open Incidents ({incidents.length})</h2>
              <Link href="/incidents" className="text-xs text-rose-300 hover:text-white">View all →</Link>
            </div>
            <div className="space-y-3">
              {incidents.map((inc:any) => (
                <div key={inc.id} className="p-3 rounded-xl bg-black/30 border border-white/10 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${inc.severity==='CRITICAL'?'bg-rose-500/20 text-rose-300 border-rose-500/30':'bg-amber-500/20 text-amber-300 border-amber-500/30'}`}>{inc.severity}</span>
                      <span className="text-xs font-semibold text-white truncate">{inc.title}</span>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-1 line-clamp-1">{inc.root_cause?.slice(0,120)}</p>
                    <p className="text-[11px] text-slate-500 mt-1">{inc.affected_columns?.slice(0,2).join(", ")} • {inc.issue_count} issues • Score {inc.quality_score_at_incident ?? "-"} </p>
                  </div>
                  <Link href={`/scans/${inc.scan_id}`} className="shrink-0 px-3 py-1 rounded-full bg-white/5 border border-white/10 text-xs text-slate-300 hover:text-white">Inspect</Link>
                </div>
              ))}
            </div>
            {reliability && (
              <div className="mt-4 pt-4 border-t border-white/10 flex items-center gap-4 text-[11px] font-mono text-slate-400">
                <span>Avg Quality Score: <b className="text-white">{reliability.avg_quality_score ?? "-"}</b></span>
                <span>Degradation: <b className={reliability.degradation?.status==='degraded'?'text-rose-300':'text-emerald-300'}>{reliability.degradation?.status}</b></span>
                <span>7d Incidents: <b className="text-white">{reliability.recent_incidents_7d}</b></span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Reliability Trend — Watchtower-inspired 30D */}
      <ReliabilityTrend data={trend} loading={dashLoading} />

      {/* Top Issues + Business Impact */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <TopIssues issues={topIssues} loading={dashLoading} />
        <BusinessImpact items={businessImpact} loading={dashLoading} />
      </div>

      {/* Ingestion & Interactive Demo Double-Bezel Section */}
      <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10 shadow-[0_12px_40px_rgba(0,0,0,0.5)] relative overflow-hidden">
        <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6 sm:p-7 shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)]">
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
            <div className="space-y-1.5 max-w-xl">
              <h2 className="text-base font-bold text-white flex items-center gap-2 tracking-tight">
                <FileUp className="w-4 h-4 text-emerald-400" />
                Ingest & Profile Dataset Batch
              </h2>
              <p className="text-xs text-slate-300 leading-relaxed">
                Upload CSV or JSON files. DataGuard generates cryptographic fingerprints, runs deterministic drift checks, applies quality bounds, and invokes the AI analyst.
              </p>
            </div>

            {/* Upload Button with nested icon CTA */}
            <div className="flex items-center gap-3">
              <label className="cursor-pointer pl-5 pr-2 py-2 rounded-full bg-emerald-500 hover:bg-emerald-400 text-emerald-950 text-xs font-bold shadow-[0_0_24px_rgba(16,185,129,0.3)] flex items-center gap-2.5 transition-all focus-within:ring-2 focus-within:ring-emerald-400">
                <span>{uploading ? "Analyzing..." : "Upload CSV / JSON"}</span>
                <span className="w-6 h-6 rounded-full bg-emerald-950/20 flex items-center justify-center text-emerald-950">
                  <Upload className="w-3.5 h-3.5 stroke-[2.5]" />
                </span>
                <input
                  type="file"
                  accept=".csv,.json"
                  onChange={handleFileUpload}
                  disabled={uploading}
                  className="hidden"
                  aria-label="Upload dataset file"
                />
              </label>
            </div>
          </div>

          {/* 1-Click Interactive Demos */}
          <div className="mt-6 pt-5 border-t border-white/[0.08] flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">
              Interactive Test Scenarios:
            </span>
            <div className="flex flex-wrap items-center gap-2.5">
              <button
                onClick={() => handleSeedDemo("orders_v1")}
                disabled={uploading}
                className="pl-3.5 pr-2 py-1.5 rounded-full text-xs font-medium bg-white/5 hover:bg-white/10 text-emerald-300 border border-white/10 hover:border-emerald-500/30 transition-all flex items-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
              >
                <span>1. Baseline Clean</span>
                <span className="w-4 h-4 rounded-full bg-emerald-500/20 flex items-center justify-center text-emerald-400">
                  <CheckCircle className="w-2.5 h-2.5 stroke-[2.5]" />
                </span>
              </button>
              <button
                onClick={() => handleSeedDemo("orders_v2_schema_drift")}
                disabled={uploading}
                className="pl-3.5 pr-2 py-1.5 rounded-full text-xs font-medium bg-white/5 hover:bg-white/10 text-amber-300 border border-white/10 hover:border-amber-500/30 transition-all flex items-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
              >
                <span>2. Schema Drift</span>
                <span className="w-4 h-4 rounded-full bg-amber-500/20 flex items-center justify-center text-amber-400">
                  <AlertTriangle className="w-2.5 h-2.5 stroke-[2.5]" />
                </span>
              </button>
              <button
                onClick={() => handleSeedDemo("orders_bad_quality")}
                disabled={uploading}
                className="pl-3.5 pr-2 py-1.5 rounded-full text-xs font-medium bg-white/5 hover:bg-white/10 text-rose-300 border border-white/10 hover:border-rose-500/30 transition-all flex items-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
              >
                <span>3. Quality Bugs</span>
                <span className="w-4 h-4 rounded-full bg-rose-500/20 flex items-center justify-center text-rose-400">
                  <XCircle className="w-2.5 h-2.5 stroke-[2.5]" />
                </span>
              </button>
            </div>
          </div>

          {/* Status Message */}
          {uploadMessage && (
            <div className="mt-4 p-3 rounded-xl bg-black/60 border border-white/10 text-xs font-mono text-emerald-300 flex items-center gap-2.5" role="status">
              <Activity className="w-4 h-4 animate-spin text-emerald-400 shrink-0" />
              <span>{uploadMessage}</span>
            </div>
          )}
        </div>
      </div>

      {/* Recent Scans Double-Bezel Table */}
      <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10 shadow-[0_12px_40px_rgba(0,0,0,0.5)]">
        <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 overflow-hidden shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)]">
          <div className="p-5 sm:p-6 border-b border-white/[0.08] flex items-center justify-between">
            <div className="flex items-center space-x-2.5">
              <div className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
              <h2 className="text-sm font-bold text-white tracking-tight">Recent Pipeline Telemetry</h2>
            </div>
            <span className="text-xs text-slate-400 font-mono">
              {scans.length} Scans Audited
            </span>
          </div>

          {loading ? (
            <div className="p-12 text-center text-slate-400 text-xs font-mono">
              Loading pipeline telemetry...
            </div>
          ) : scans.length === 0 ? (
            <div className="p-12 text-center text-slate-400">
              <p className="text-sm font-semibold text-white">No scans executed yet</p>
              <p className="text-xs text-slate-400 mt-1">
                Click one of the interactive demo buttons above to see DataGuard in action.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-black/30 text-[10px] font-bold text-slate-400 uppercase tracking-[0.15em] border-b border-white/[0.06]">
                  <tr>
                    <th className="px-6 py-3.5">Pipeline Run</th>
                    <th className="px-6 py-3.5">Status</th>
                    <th className="px-6 py-3.5">Deterministic Bounds</th>
                    <th className="px-6 py-3.5">Quality Score</th>
                    <th className="px-6 py-3.5">Business Impact</th>
                    <th className="px-6 py-3.5">AI Analysis</th>
                    <th className="px-6 py-3.5">Completed</th>
                    <th className="px-6 py-3.5 text-right">Inspect</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.06]">
                  {scans.map((scan) => {
                    const isCritical = scan.critical_count > 0;
                    const isWarning = scan.warning_count > 0 && !isCritical;

                    return (
                      <tr key={scan.id} className="hover:bg-white/[0.02] transition-colors">
                        <td className="px-6 py-4">
                          <div className="font-mono text-xs font-bold text-white">
                            Scan #{scan.id}
                          </div>
                          <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                            Dataset #{scan.dataset_id}
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          {isCritical ? (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-rose-500/15 text-rose-300 border border-rose-500/30 font-mono">
                              <XCircle className="w-3 h-3 text-rose-400" /> CRITICAL
                            </span>
                          ) : isWarning ? (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30 font-mono">
                              <AlertTriangle className="w-3 h-3 text-amber-400" /> WARNING
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-mono">
                              <CheckCircle className="w-3 h-3 text-emerald-400" /> HEALTHY
                            </span>
                          )}
                        </td>
                        <td className="px-6 py-4 text-xs font-mono">
                          <div className="flex items-center gap-2 text-[11px]">
                            <span className="text-rose-400 font-semibold">{scan.critical_count} critical</span>
                            <span className="text-slate-600">•</span>
                            <span className="text-amber-400 font-medium">{scan.warning_count} warnings</span>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${scan.quality_score >= 90 ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20' : scan.quality_score >= 75 ? 'bg-amber-500/10 text-amber-300 border-amber-500/20' : 'bg-rose-500/10 text-rose-300 border-rose-500/20'}`}>{scan.quality_score ?? "-"}</span>
                        </td>
                        <td className="px-6 py-4">
                          {isCritical ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-500/10 text-rose-300 border border-rose-500/20">At Risk</span>
                          ) : isWarning ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/10 text-amber-300 border border-amber-500/20">Warning</span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">Healthy</span>
                          )}
                        </td>
                        <td className="px-6 py-4 text-xs">
                          {scan.ai_analyses && scan.ai_analyses.length > 0 ? (
                            <span className="inline-flex items-center gap-1.5 text-teal-300 font-medium bg-teal-500/10 px-2.5 py-0.5 rounded-full border border-teal-500/20 text-[11px]">
                              <Sparkles className="w-3 h-3 text-teal-400" /> Diagnosed
                            </span>
                          ) : (
                            <span className="text-slate-500 text-xs">Pending</span>
                          )}
                        </td>
                        <td className="px-6 py-4 text-xs text-slate-400 font-mono">
                          {new Date(scan.completed_at).toLocaleTimeString()}
                        </td>
                        <td className="px-6 py-4 text-right">
                          <Link
                            href={`/scans/${scan.id}`}
                            className="inline-flex items-center gap-1.5 pl-3 pr-1.5 py-1 rounded-full text-xs font-semibold bg-white/5 hover:bg-white/10 text-slate-200 border border-white/10 hover:border-white/20 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
                          >
                            <span>Review</span>
                            <span className="w-4 h-4 rounded-full bg-white/10 flex items-center justify-center text-slate-300">
                              <ArrowRight className="w-2.5 h-2.5" />
                            </span>
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
