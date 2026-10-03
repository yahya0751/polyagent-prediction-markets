import { useMemo } from "react";
import { fmtPct, fmtUsd, cls } from "../lib/fmt";

export default function TradesTable({ scan }) {
  const rows = useMemo(() => {
    const opps = scan?.opportunities || [];
    // Convert opportunities → fake "recent" trades for display
    return opps.slice(0, 10).map((o, i) => ({
      ...o,
      ts: Date.now() / 1000 - (i + 1) * 240 + Math.random() * 30,
      pnl: (Math.random() - 0.42) * 80,
    }));
  }, [scan]);

  return (
    <div className="panel p-0 overflow-hidden">
      <div className="px-3 py-2 flex items-center justify-between border-b border-ink-700/60">
        <div className="flex items-center gap-2">
          <span className="label-mono">Recent trades</span>
          <span className="chip-zinc">simulated</span>
        </div>
        <span className="text-[10px] text-zinc-500 num">{rows.length} fills</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-[11px] num">
          <thead>
            <tr className="text-[9px] uppercase tracking-widest text-zinc-500 border-b border-ink-700/60">
              <th className="text-left py-2 px-3 font-medium">Time</th>
              <th className="text-left py-2 font-medium">Side</th>
              <th className="text-left py-2 font-medium">Market</th>
              <th className="text-right py-2 font-medium">Price</th>
              <th className="text-right py-2 font-medium">Size</th>
              <th className="text-right py-2 font-medium">PnL</th>
              <th className="text-right py-2 px-3 font-medium">Conf</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="py-6 text-center text-zinc-500">
                  No trades yet — run a scan.
                </td>
              </tr>
            )}
            {rows.map((r, i) => {
              const d = new Date(r.ts * 1000);
              const time = `${String(d.getUTCHours()).padStart(2,"0")}:${String(d.getUTCMinutes()).padStart(2,"0")}:${String(d.getUTCSeconds()).padStart(2,"0")}`;
              return (
                <tr
                  key={i}
                  className="border-b border-ink-700/30 hover:bg-ink-800/40 transition"
                >
                  <td className="py-2 px-3 text-zinc-500">{time}</td>
                  <td className={cls("py-2", r.side === "YES" ? "text-neon-green" : "text-neon-red")}>{r.side}</td>
                  <td className="py-2 text-zinc-200 max-w-[280px] truncate">{r.market}</td>
                  <td className="py-2 text-right text-zinc-200">{fmtPct(r.market_price)}</td>
                  <td className="py-2 text-right text-zinc-300">{fmtUsd(r.size_suggested, 0)}</td>
                  <td className={cls("py-2 text-right", r.pnl >= 0 ? "text-neon-green" : "text-neon-red")}>
                    {r.pnl >= 0 ? "+" : ""}{r.pnl.toFixed(2)}
                  </td>
                  <td className="py-2 px-3 text-right text-neon-purple">{fmtPct(r.confidence, 0)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
