import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { cls, fmtPct } from "../lib/fmt";

function Row({ row, side, max }) {
  const isBid = side === "bid";
  const pct = Math.min(100, (row.size / max) * 100);
  return (
    <div className="relative grid grid-cols-3 items-center text-[11px] py-[3px] px-2 num group">
      <div
        className={cls(
          "absolute inset-y-0 right-0",
          isBid ? "bg-neon-green/10" : "bg-neon-red/10"
        )}
        style={{ width: `${pct}%` }}
      />
      <div className={cls("relative", isBid ? "text-neon-green" : "text-neon-red")}>
        {fmtPct(row.price, 2)}
      </div>
      <div className="relative text-right text-zinc-300">{row.size.toLocaleString()}</div>
      <div className="relative text-right text-zinc-500 group-hover:text-zinc-300">
        {((row.price * row.size) / 100).toFixed(0)}
      </div>
    </div>
  );
}

export default function OrderBook({ marketId }) {
  const [book, setBook] = useState({ bids: [], asks: [] });

  useEffect(() => {
    let cancel = false;
    const load = () =>
      api
        .orderbook(marketId)
        .then((d) => !cancel && setBook(d))
        .catch(() => {});
    load();
    const id = setInterval(load, 4000);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, [marketId]);

  const max =
    Math.max(
      ...book.bids.map((r) => r.size),
      ...book.asks.map((r) => r.size),
      1
    );
  const bestBid = book.bids[0]?.price ?? 0;
  const bestAsk = book.asks[0]?.price ?? 0;
  const spread = bestAsk - bestBid;
  const mid = (bestAsk + bestBid) / 2;

  return (
    <div className="panel p-0 overflow-hidden">
      <div className="px-3 py-2 flex items-center justify-between border-b border-ink-700/60">
        <div className="flex items-center gap-2">
          <span className="label-mono">Order Book</span>
          <span className="chip-zinc">YES side</span>
        </div>
        <span className="text-[10px] text-zinc-500 num">depth · 8</span>
      </div>

      <div className="grid grid-cols-3 px-2 pt-2 pb-1 text-[9px] uppercase tracking-widest text-zinc-500">
        <div>Price</div>
        <div className="text-right">Size</div>
        <div className="text-right">Total</div>
      </div>

      {/* Asks reversed so highest is on top */}
      <div className="space-y-[1px]">
        {[...book.asks].reverse().map((r, i) => (
          <Row key={`a${i}`} row={r} side="ask" max={max} />
        ))}
      </div>

      <div className="my-1 mx-2 px-2 py-1.5 rounded border border-ink-700/80 bg-ink-850 flex items-center justify-between text-[11px]">
        <span className="text-zinc-500 label-mono">spread</span>
        <span className="num text-zinc-200">{fmtPct(spread, 3)}</span>
        <span className="text-zinc-500 label-mono">mid</span>
        <span className="num text-neon-green">{fmtPct(mid, 3)}</span>
      </div>

      <div className="space-y-[1px] pb-2">
        {book.bids.map((r, i) => (
          <Row key={`b${i}`} row={r} side="bid" max={max} />
        ))}
      </div>
    </div>
  );
}
