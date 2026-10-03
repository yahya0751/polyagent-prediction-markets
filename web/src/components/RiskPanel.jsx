import { fmtUsd, cls } from "../lib/fmt";

function Bar({ value, max, tone = "green" }) {
  const pct = Math.max(0, Math.min(1, value / max)) * 100;
  const color =
    tone === "green" ? "from-neon-green to-neon-cyan"
    : tone === "yellow" ? "from-neon-yellow to-neon-yellow/60"
    : "from-neon-red to-neon-red/60";
  return (
    <div className="h-[6px] rounded-full bg-ink-800 overflow-hidden">
      <div className={cls("h-full bg-gradient-to-r", color)} style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function RiskPanel({ risk, onKill, onUnkill, killed }) {
  if (!risk) return null;

  const lossUsed = Math.max(0, -risk.daily_pnl_usd);
  const lossPct = lossUsed / risk.daily_loss_limit_usd;
  const exposurePct = risk.exposure_usd / 5000;

  return (
    <div className="panel p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="label-mono">Risk Controls</span>
          <span className="chip-yellow">PAPER</span>
        </div>
        {killed ? (
          <span className="chip-red animate-pulseSoft">KILL ENGAGED</span>
        ) : (
          <span className="chip-green">ARMED</span>
        )}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3">
        <div className="p-3 rounded border border-ink-700/70 bg-ink-850/60">
          <div className="label-mono">Daily PnL</div>
          <div className={cls("display num text-lg mt-0.5", risk.daily_pnl_usd >= 0 ? "text-neon-green" : "text-neon-red")}>
            {risk.daily_pnl_usd >= 0 ? "+" : ""}{fmtUsd(risk.daily_pnl_usd)}
          </div>
          <div className="text-[10px] text-zinc-500 mt-0.5">
            limit {fmtUsd(risk.daily_loss_limit_usd)}
          </div>
        </div>
        <div className="p-3 rounded border border-ink-700/70 bg-ink-850/60">
          <div className="label-mono">Active positions</div>
          <div className="display num text-lg text-zinc-100 mt-0.5">{risk.active_positions}</div>
          <div className="text-[10px] text-zinc-500 mt-0.5">
            max trade {fmtUsd(risk.max_trade_size_usd)}
          </div>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        <div>
          <div className="flex justify-between items-baseline">
            <span className="label-mono">Loss limit usage</span>
            <span className="num text-[11px] text-zinc-300">
              {fmtUsd(lossUsed)} / {fmtUsd(risk.daily_loss_limit_usd)}
            </span>
          </div>
          <div className="mt-1">
            <Bar value={lossUsed} max={risk.daily_loss_limit_usd} tone={lossPct > 0.7 ? "red" : lossPct > 0.4 ? "yellow" : "green"} />
          </div>
        </div>
        <div>
          <div className="flex justify-between items-baseline">
            <span className="label-mono">Exposure</span>
            <span className="num text-[11px] text-zinc-300">{fmtUsd(risk.exposure_usd)}</span>
          </div>
          <div className="mt-1">
            <Bar value={risk.exposure_usd} max={5000} tone={exposurePct > 0.7 ? "yellow" : "green"} />
          </div>
        </div>
      </div>

      <div className="mt-4 flex gap-2">
        {!killed ? (
          <button
            onClick={onKill}
            className="flex-1 py-2 rounded border border-neon-red/40 bg-neon-red/5 text-neon-red text-[11px] uppercase tracking-widest hover:bg-neon-red/10 hover:shadow-glow-red transition"
          >
            ⏻ Engage kill switch
          </button>
        ) : (
          <button
            onClick={onUnkill}
            className="flex-1 py-2 rounded border border-neon-green/40 bg-neon-green/5 text-neon-green text-[11px] uppercase tracking-widest hover:bg-neon-green/10 transition"
          >
            ↻ Reset
          </button>
        )}
      </div>

      <div className="mt-3 text-[10px] text-zinc-500 leading-relaxed border-t border-ink-700/40 pt-3">
        <span className="text-neon-yellow">⚠</span> This is a paper-trading demo. Nothing here constitutes financial advice.
        Live trading is disabled at the web layer.
      </div>
    </div>
  );
}
