import { fmtPct, fmtUsd, cls } from "../lib/fmt";

function Stat({ label, value, tone = "zinc", sub }) {
  const color =
    tone === "green" ? "text-neon-green"
    : tone === "red" ? "text-neon-red"
    : tone === "yellow" ? "text-neon-yellow"
    : tone === "purple" ? "text-neon-purple"
    : "text-zinc-100";
  return (
    <div className="flex items-baseline justify-between gap-3 py-2 border-b border-ink-700/40 last:border-0">
      <div className="label-mono">{label}</div>
      <div className="text-right">
        <div className={cls("display num text-[16px] font-semibold tracking-tight", color)}>{value}</div>
        {sub && <div className="text-[10px] text-zinc-500 num">{sub}</div>}
      </div>
    </div>
  );
}

export default function AgentCard({ scan, market }) {
  // Derive demo agent KPIs from the scan response.
  const opp = scan?.best;
  const pnl = 142.36;
  const roi = 0.184;
  const winRate = 0.612;
  const trades = 47;

  return (
    <div className="panel panel-glow p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-neon-green shadow-[0_0_8px_#00ff9c] animate-pulseSoft" />
          <span className="label-mono">Agent</span>
        </div>
        <span className="chip-green">ACTIVE</span>
      </div>
      <div className="mt-2">
        <div className="display text-2xl font-bold text-zinc-50 tracking-tight">
          ORACLE-<span className="text-neon-green">7</span>
        </div>
        <div className="text-[11px] text-zinc-500 mt-0.5">
          poly-α · v0.1.2 · {opp ? "scouting" : "idle"}
        </div>
      </div>

      <div className="mt-4 divider-h" />

      <div className="mt-2">
        <Stat label="Simulated PnL" value={fmtUsd(pnl)} tone="green" sub="last 24h" />
        <Stat label="ROI" value={fmtPct(roi)} tone="green" />
        <Stat label="Win rate" value={fmtPct(winRate)} tone="yellow" sub={`${trades} trades`} />
        <Stat label="Trades" value={trades} />
        <Stat
          label="Focus"
          value={market?.title?.slice(0, 26) + (market?.title?.length > 26 ? "…" : "") || "—"}
          tone="purple"
          sub={market?.category}
        />
      </div>

      <div className="mt-4 p-3 rounded-md border border-neon-yellow/20 bg-neon-yellow/5">
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.2em] text-neon-yellow">
          <span>⚠</span> Paper trading
        </div>
        <p className="text-[11px] text-zinc-400 mt-1 leading-relaxed">
          All execution is simulated. No on-chain orders are submitted from this UI.
        </p>
      </div>
    </div>
  );
}
