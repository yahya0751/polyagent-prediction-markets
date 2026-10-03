import { fmtPct, fmtUsd, cls } from "../lib/fmt";

function MetricBar({ label, value, max = 1, tone = "green" }) {
  const pct = Math.max(0, Math.min(1, value / max)) * 100;
  const color =
    tone === "green" ? "from-neon-green/80 to-neon-green/30"
    : tone === "purple" ? "from-neon-purple/80 to-neon-purple/30"
    : tone === "yellow" ? "from-neon-yellow/80 to-neon-yellow/30"
    : "from-neon-red/80 to-neon-red/30";
  return (
    <div>
      <div className="flex justify-between items-baseline">
        <span className="label-mono">{label}</span>
        <span className="num text-[12px] text-zinc-200">{fmtPct(value, 1)}</span>
      </div>
      <div className="mt-1 h-[5px] rounded-full bg-ink-800 overflow-hidden">
        <div
          className={cls("h-full bg-gradient-to-r", color)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function SignalPanel({ scan, onRescan, scanning }) {
  const best = scan?.best;

  if (!best) {
    return (
      <div className="panel p-4">
        <div className="label-mono">Best signal</div>
        <div className="mt-2 text-zinc-400 text-[12px]">No actionable edge in current scan.</div>
        <button
          onClick={onRescan}
          className="mt-3 text-[11px] text-neon-green border border-neon-green/30 px-3 py-1.5 rounded hover:bg-neon-green/10 transition"
        >
          {scanning ? "Scanning…" : "Run scan"}
        </button>
      </div>
    );
  }

  const riskTone =
    best.risk === "LOW" ? "green" : best.risk === "MED" ? "yellow" : "red";

  return (
    <div className="panel panel-glow p-4 relative overflow-hidden">
      <div className="absolute -top-px left-4 right-4 h-px bg-gradient-to-r from-transparent via-neon-green to-transparent" />
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="label-mono">Best signal</span>
          <span className="chip-green animate-pulseSoft">LIVE</span>
        </div>
        <button
          onClick={onRescan}
          disabled={scanning}
          className="text-[10px] uppercase tracking-widest text-zinc-400 border border-ink-700 hover:border-neon-green/40 hover:text-neon-green px-2.5 py-1 rounded transition"
        >
          {scanning ? "scanning…" : "rescan"}
        </button>
      </div>

      <div className="mt-3">
        <div className="flex items-baseline gap-2">
          <span className={cls("display num text-2xl font-bold", best.side === "YES" ? "text-neon-green" : "text-neon-red")}>
            {best.side}
          </span>
          <span className="text-zinc-300 text-[13px] truncate">{best.market}</span>
        </div>
        <div className="text-[11px] text-zinc-500 mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
          <span>model <span className="text-zinc-200 num">{fmtPct(best.model_price)}</span></span>
          <span>market <span className="text-zinc-200 num">{fmtPct(best.market_price)}</span></span>
          <span className="text-neon-green num">edge {fmtPct(best.edge)}</span>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <div className="p-3 rounded border border-ink-700/70 bg-ink-850/60">
          <div className="label-mono">Entry size</div>
          <div className="display num text-lg text-zinc-100 mt-0.5">{fmtUsd(best.size_suggested, 0)}</div>
        </div>
        <div className="p-3 rounded border border-ink-700/70 bg-ink-850/60">
          <div className="label-mono">Expected value</div>
          <div className="display num text-lg text-neon-green mt-0.5">{fmtPct(best.expected_value, 2)}</div>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        <MetricBar label="Confidence" value={best.confidence} tone="purple" />
        <MetricBar label="Edge magnitude" value={Math.abs(best.edge)} max={0.2} tone="green" />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 text-[11px]">
        <div>
          <div className="label-mono">Catalyst</div>
          <div className="text-zinc-200 mt-0.5">{best.catalyst}</div>
        </div>
        <div className="text-right">
          <div className="label-mono">Risk</div>
          <div className="mt-0.5">
            <span className={cls(
              riskTone === "green" ? "chip-green" : riskTone === "yellow" ? "chip-yellow" : "chip-red"
            )}>
              {best.risk}
            </span>
          </div>
        </div>
      </div>

      <div className="mt-4 flex gap-2">
        <button
          disabled
          title="Live trading disabled in web layer"
          className="flex-1 py-2 rounded border border-neon-green/20 bg-neon-green/5 text-neon-green/60 text-[11px] uppercase tracking-widest cursor-not-allowed"
        >
          Execute (paper)
        </button>
        <button className="px-3 py-2 rounded border border-ink-700 text-zinc-400 text-[11px] uppercase tracking-widest hover:text-zinc-200 hover:border-ink-600">
          Skip
        </button>
      </div>
    </div>
  );
}
