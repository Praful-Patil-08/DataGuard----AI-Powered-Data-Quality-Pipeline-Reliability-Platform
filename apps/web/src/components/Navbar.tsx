import React from "react";
import Link from "next/link";
import { ShieldCheck, Database, Terminal, ArrowUpRight, Cpu } from "lucide-react";

export const Navbar = () => {
  return (
    <header className="sticky top-4 z-50 px-4 sm:px-6 max-w-6xl mx-auto w-full">
      <div className="rounded-full bg-slate-950/75 backdrop-blur-2xl border border-white/10 shadow-[0_8px_32px_rgba(0,0,0,0.5)] p-1.5 pl-5 pr-2 flex items-center justify-between transition-all">
        {/* Brand identity */}
        <Link href="/" className="flex items-center space-x-3 group">
          <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-emerald-500 to-cyan-400 flex items-center justify-center shadow-[0_0_16px_rgba(16,185,129,0.35)] group-hover:scale-105 transition-transform duration-300">
            <ShieldCheck className="w-4 h-4 text-emerald-950 font-black stroke-[2.5]" />
          </div>
          <div className="flex items-center space-x-2">
            <span className="text-sm font-extrabold tracking-tight text-white flex items-center gap-2">
              DataGuard
            </span>
            <span className="hidden sm:inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono font-medium">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              v1.0.0
            </span>
          </div>
        </Link>

        {/* Navigation Actions */}
        <nav className="flex items-center space-x-1 sm:space-x-2">
          <Link
            href="/"
            className="flex items-center space-x-1.5 px-3.5 py-1.5 rounded-full text-xs font-medium text-slate-300 hover:text-white hover:bg-white/5 transition-all"
          >
            <Database className="w-3.5 h-3.5 text-emerald-400" />
            <span>Telemetry</span>
          </Link>
          <a
            href="http://localhost:8001/docs"
            target="_blank"
            rel="noreferrer"
            className="flex items-center space-x-1.5 px-3.5 py-1.5 rounded-full text-xs font-medium text-slate-400 hover:text-white hover:bg-white/5 transition-all"
          >
            <Terminal className="w-3.5 h-3.5 text-cyan-400" />
            <span className="hidden sm:inline">OpenAPI Docs</span>
            <span className="sm:hidden">Docs</span>
            <ArrowUpRight className="w-3 h-3 opacity-60" />
          </a>
        </nav>
      </div>
    </header>
  );
};
