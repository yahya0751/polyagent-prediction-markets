import { useMemo } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import { fmtPct, cls } from "../lib/fmt";

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  const v = payload[0].value;
  const date = new Date(label * 1000);
  const hh = String(date.getUTCHours()).padStart(2, "0");
  const mm = String(date.getUTCMinutes()).padStart(2, "0");
  return (
    <div className="bg-ink-900/95 border border-ink-700 rounded px-2.5 py-1.5 text-[11px] shadow-xl">
      <div className="text-zinc-500">{hh}:{mm} UTC</div>
      <div className="num text-neon-green">{fmtPct(v, 2)}</div>
    </div>
  );
}

export default function Chart({ market, markets, onSelect }) {
  const data = market?.series || [];
  const first = data[0]?.p;
  const last = data[data.length - 1]?.p;
  const change = first && last ? last - first : 0;
  const changePct = first ? change / first : 0;
  const up = change >= 0;

  const stroke = up ? "#00ff9c" : "#ff3355";
  const gradId = useMemo(() => `g-${market?.id || "x"}-${up ? "u" : "d"}`, [market?.id, up]);

  return (
    <div className="panel p-0 overflow-hidden">
      {/* tab strip */}
      <div className="flex items-center gap-1 px-3 pt-3 pb-2 overflow-x-auto ticker">
        {(markets || []).map((m) => {
          const active = m.id === market?.id;
          return (
            <button
              key={m.id}
              onClick={() => onSelect?.(m)}
              className={cls(
                "shrink-0 text-[11px] px-2.5 py-1.5 rounded border transition-all",
                active
                  ? "border-neon-green/40 bg-neon-green/5 text-neon-green shadow-[0_0_12px_rgba(0,255,156,0.1)]"
                  : "border-ink-700/70 text-zinc-400 hover:text-zinc-200 hover:border-ink-600"
              )}
            >
              <span className="text-zinc-500 mr-1">{m.category?.slice(0, 3).toUpperCase()}</span>
              {m.title.length > 36 ? m.title.slice(0, 36) + "…" : m.title}
              <span className={cls("ml-2 num", active ? "text-neon-green" : "text-zinc-500")}>
                {fmtPct(m.yes_price)}
              </span>
            </button>
          );
        })}
      </div>

      <div className="px-4 py-3 border-y border-ink-700/60 flex items-end justify-between gap-4">
        <div>
          <div className="label-mono">Now trading</div>
          <div className="display text-lg font-semibold text-zinc-50 tracking-tight">
            {market?.title || "—"}
          </div>
          <div className="flex items-center gap-3 mt-1 text-[11px]">
            <span className="chip-zinc">{market?.category}</span>
            <span className="text-zinc-500">vol/24h</span>
            <span className="text-zinc-200 num">${(market?.volume_24h || 0).toLocaleString()}</span>
            <span className="text-zinc-500">liq</span>
            <span className="text-zinc-200 num">${(market?.liquidity || 0).toLocaleString()}</span>
          </div>
        </div>
        <div className="text-right">
          <div className="label-mono">Yes price</div>
          <div className={cls("display text-3xl font-bold num tracking-tight", up ? "text-neon-green" : "text-neon-red")}>
            {fmtPct(market?.yes_price)}
          </div>
          <div className={cls("text-[11px] num", up ? "text-neon-green" : "text-neon-red")}>
            {up ? "▲" : "▼"} {fmtPct(Math.abs(changePct))}
          </div>
        </div>
      </div>

      <div className="h-[260px] md:h-[320px] px-1 py-2">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 10, right: 18, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={stroke} stopOpacity={0.32} />
                <stop offset="100%" stopColor={stroke} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#11161d" strokeDasharray="0" />
            <XAxis
              dataKey="t"
              tickFormatter={(t) => {
                const d = new Date(t * 1000);
                return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
              }}
              tick={{ fill: "#52606d", fontSize: 10, fontFamily: "JetBrains Mono" }}
              axisLine={{ stroke: "#161c25" }}
              tickLine={false}
              minTickGap={40}
            />
            <YAxis
              domain={["auto", "auto"]}
              tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
              tick={{ fill: "#52606d", fontSize: 10, fontFamily: "JetBrains Mono" }}
              axisLine={false}
              tickLine={false}
              width={42}
              orientation="right"
            />
            <Tooltip content={<CustomTooltip />} cursor={{ stroke: "#2a3340", strokeDasharray: "3 3" }} />
            {first && (
              <ReferenceLine
                y={first}
                stroke="#2a3340"
                strokeDasharray="2 4"
                label={{ value: "open", fill: "#52606d", fontSize: 9, position: "left" }}
              />
            )}
            <Area
              type="monotone"
              dataKey="p"
              stroke={stroke}
              strokeWidth={1.6}
              fill={`url(#${gradId})`}
              isAnimationActive={false}
              dot={false}
              activeDot={{ r: 3, stroke, strokeWidth: 1, fill: "#05070a" }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
