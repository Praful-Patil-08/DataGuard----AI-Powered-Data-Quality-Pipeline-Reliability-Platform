import React from "react";
import { Activity, TrendingUp } from "lucide-react";

interface TrendPoint {
  date: string;
  healthy: number;
  warning: number;
  critical: number;
  total: number;
}

interface Props {
  data: TrendPoint[];
  loading?: boolean;
}

export const ReliabilityTrend = ({ data, loading }: Props) => {
  if (loading) {
    return (
      <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10">
        <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6 text-xs font-mono text-slate-400">
          Loading reliability trend…
        </div>
      </div>
    );
  }
  if (!data || data.length === 0) {
    return (
      <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10">
        <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-8 text-center text-slate-400">
          <p className="text-sm font-semibold text-white">No trend data yet</p>
          <p className="text-xs mt-1">Run a scan to populate the 30-day reliability view.</p>
        </div>
      </div>
    );
  }

  const max = Math.max(1, ...data.map(d => d.total));
  const W = 600;
  const H = 120;
  const pad = 12;

  const toPath = (key: keyof TrendPoint, color: string) => {
    const points = data.map((d, i) => {
      const x = pad + (i / Math.max(1, data.length - 1)) * (W - pad * 2);
      const y = H - pad - ((d[key] as number) / max) * (H - pad * 2);
      return { x, y };
    });
    if (points.length === 0) return "";
    let d = `M ${points[0].x} ${points[0].y}`;
    for (let i = 1; i < points.length; i++) {
      const prev = points[i - 1];
      const cur = points[i];
      const cpx = (prev.x + cur.x) / 2;
      d += ` C ${cpx} ${prev.y}, ${cpx} ${cur.y}, ${cur.x} ${cur.y}`;
    }
    return d;
  };

  const areaPath = (key: keyof TrendPoint) => {
    const line = toPath(key, "");
    if (!line) return "";
    const lastX = pad + (W - pad * 2);
    const firstX = pad;
    return `${line} L ${lastX} ${H - pad} L ${firstX} ${H - pad} Z`;
  };

  const dates = data.map(d => d.date.slice(5)); // MM-DD

  return (
    <div className="rounded-[1.75rem] p-1.5 bg-white/[0.03] ring-1 ring-white/10 shadow-[0_12px_40px_rgba(0,0,0,0.5)]">
      <div className="rounded-[calc(1.75rem-0.375rem)] bg-gradient-to-b from-slate-900/90 to-slate-950 p-6 sm:p-7 shadow-[inset_0_1px_1px_rgba(255,255,255,0.06)]">
        <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded-xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
              <Activity className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white tracking-tight flex items-center gap-2">
                Reliability Trend <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-slate-400 font-mono">30D</span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">Healthy vs warning vs critical scans per day</p>
            </div>
          </div>
          <div className="hidden sm:flex items-center gap-3 text-[10px] font-mono">
            <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-emerald-400" />Healthy</span>
            <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-amber-400" />Warning</span>
            <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-rose-400" />Critical</span>
          </div>
        </div>

        <div className="mt-6 relative">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[140px]" preserveAspectRatio="none">
            {/* grid */}
            {[0, 1, 2].map(i => (
              <line key={i} x1={pad} x2={W - pad} y1={pad + (i * (H - pad * 2) / 2)} y2={pad + (i * (H - pad * 2) / 2)} stroke="rgba(255,255,255,0.06)" strokeDasharray="3 3" />
            ))}
            {/* areas */}
            <path d={areaPath("critical")} fill="rgba(244,63,94,0.12)" stroke="none" />
            <path d={areaPath("warning")} fill="rgba(251,146,60,0.10)" stroke="none" />
            <path d={areaPath("healthy")} fill="rgba(16,185,129,0.10)" stroke="none" />
            {/* lines */}
            <path d={toPath("critical", "rose")} fill="none" stroke="rgba(244,63,94,0.85)" strokeWidth="2" strokeLinecap="round" />
            <path d={toPath("warning", "amber")} fill="none" stroke="rgba(251,146,60,0.85)" strokeWidth="2" strokeLinecap="round" />
            <path d={toPath("healthy", "emerald")} fill="none" stroke="rgba(16,185,129,0.9)" strokeWidth="2.2" strokeLinecap="round" />
          </svg>
          <div className="flex justify-between mt-2 text-[10px] font-mono text-slate-500">
            <span>{dates[0]}</span>
            <span>{dates[Math.floor(dates.length/2)]}</span>
            <span>{dates[dates.length-1]}</span>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-3 text-center">
          <div className="rounded-xl bg-emerald-500/5 border border-emerald-500/15 p-3">
            <div className="text-[10px] uppercase tracking-widest font-semibold text-emerald-400">Healthy</div>
            <div className="text-lg font-mono font-bold text-white mt-1">{data.reduce((a,b)=>a+b.healthy,0)}</div>
          </div>
          <div className="rounded-xl bg-amber-500/5 border border-amber-500/15 p-3">
            <div className="text-[10px] uppercase tracking-widest font-semibold text-amber-400">Warning</div>
            <div className="text-lg font-mono font-bold text-white mt-1">{data.reduce((a,b)=>a+b.warning,0)}</div>
          </div>
          <div className="rounded-xl bg-rose-500/5 border border-rose-500/15 p-3">
            <div className="text-[10px] uppercase tracking-widest font-semibold text-rose-400">Critical</div>
            <div className="text-lg font-mono font-bold text-white mt-1">{data.reduce((a,b)=>a+b.critical,0)}</div>
          </div>
        </div>
      </div>
    </div>
  );
};
