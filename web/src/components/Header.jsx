import { useEffect, useState } from "react";
import { cls } from "../lib/fmt";

function UtcClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const hh = String(now.getUTCHours()).padStart(2, "0");
  const mm = String(now.getUTCMinutes()).padStart(2, "0");
  const ss = String(now.getUTCSeconds()).padStart(2, "0");
  const yyyy = now.getUTCFullYear();
  const mo = String(now.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(now.getUTCDate()).padStart(2, "0");
  return (
    <div className="text-right leading-tight">
      <div className="label-mono">UTC</div>
      <div className="num text-zinc-200 text-[13px] tracking-wider">
        {yyyy}-{mo}-{dd} <span className="text-neon-green">{hh}:{mm}:{ss}</span>
      </div>
    </div>
  );
}

function StatusDot({ tone = "green", pulse = true }) {
  const color =
    tone === "green" ? "bg-neon-green shadow-[0_0_8px_#00ff9c]"
    : tone === "red" ? "bg-neon-red shadow-[0_0_8px_#ff3355]"
    : tone === "yellow" ? "bg-neon-yellow shadow-[0_0_8px_#ffd23f]"
    : "bg-zinc-500";
  return <span className={cls("inline-block w-1.5 h-1.5 rounded-full", color, pulse && "animate-pulseSoft")} />;
}

export default function Header({ status }) {
  const ai = status?.ai_enabled;
  const killed = status?.kill_switch;
  const mode = status?.mode || "PAPER_TRADING";

  return (
    <header className="relative z-10 border-b border-ink-700/80 bg-ink-900/60 backdrop-blur-md">
      <div className="absolute inset-x-0 -bottom-px h-px bg-gradient-to-r from-transparent via-neon-green/40 to-transparent" />
      <div className="px-5 py-3 flex items-center gap-6">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="relative w-8 h-8 rounded-md border border-neon-green/40 bg-neon-green/5 grid place-items-center shadow-glow">
            <svg viewBox="0 0 32 32" className="w-5 h-5">
              <path d="M3 24 L11 12 L15 18 L20 6 L29 24" stroke="#00ff9c" strokeWidth="2.4" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
              <circle cx="20" cy="6" r="1.8" fill="#00ff9c"/>
            </svg>
          </div>
          <div className="leading-tight">
            <div className="display text-[15px] font-semibold tracking-wide">
              <span className="text-zinc-100">POLY</span>
              <span className="text-neon-green">AGENT</span>
              <span className="text-zinc-500 ml-2 text-[11px] uppercase tracking-[0.3em]">// terminal</span>
            </div>
            <div className="label-mono">v0.1 · prediction-market intelligence</div>
          </div>
        </div>

        <div className="hidden md:block w-px h-8 bg-ink-700/80" />

        {/* Mode */}
        <div className="flex items-center gap-2">
          <StatusDot tone="yellow" />
          <div className="leading-tight">
            <div className="label-mono">Mode</div>
            <div className="text-[12px] tracking-wider text-neon-yellow">
              {mode} <span className="text-zinc-500">· DEMO</span>
            </div>
          </div>
        </div>

        {/* AI */}
        <div className="flex items-center gap-2">
          <StatusDot tone={ai ? "green" : "red"} pulse={ai} />
          <div className="leading-tight">
            <div className="label-mono">AI</div>
            <div className={cls("text-[12px] tracking-wider", ai ? "text-neon-green" : "text-zinc-400")}>
              {ai ? "ENABLED" : "DISABLED"}
            </div>
          </div>
        </div>

        {/* Kill */}
        <div className="flex items-center gap-2">
          <StatusDot tone={killed ? "red" : "green"} pulse={!killed} />
          <div className="leading-tight">
            <div className="label-mono">Kill switch</div>
            <div className={cls("text-[12px] tracking-wider", killed ? "text-neon-red" : "text-neon-green")}>
              {killed ? "ENGAGED" : "ARMED"}
            </div>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-6">
          <div className="hidden lg:flex items-center gap-2 text-[10px] uppercase tracking-[0.25em] text-zinc-500">
            <span className="blink text-neon-green">●</span> live
            <span className="text-zinc-600">·</span>
            <span className="text-zinc-400">paper-trading only</span>
          </div>
          <UtcClock />
        </div>
      </div>
    </header>
  );
}
