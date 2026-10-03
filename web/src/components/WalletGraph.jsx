import { useMemo, useState } from "react";
import { fmtPct, fmtUsd, shortAddr, cls } from "../lib/fmt";

// Map cluster type → glow color
const CLUSTER_COLORS = {
  whale: "#a855f7",
  smart: "#00ff9c",
  fund: "#22d3ee",
  retail: "#52606d",
  mm: "#ffd23f",
  influencer: "#ff7ab8",
  suspicious: "#ff3355",
};

function layout(wallets, w, h) {
  // Simple deterministic radial layout, with whales at center
  const center = { x: w / 2, y: h / 2 };
  const order = [...wallets].sort((a, b) => b.skill_score - a.skill_score);
  const positions = {};
  order.forEach((wallet, i) => {
    if (i === 0) {
      positions[wallet.address] = center;
      return;
    }
    const ringSize = i < 5 ? 4 : order.length - 5;
    const ringIdx = i < 5 ? i - 1 : i - 5;
    const radius = i < 5 ? Math.min(w, h) * 0.22 : Math.min(w, h) * 0.42;
    const angle =
      (ringIdx / Math.max(1, ringSize)) * Math.PI * 2 + (i < 5 ? 0.6 : 1.2);
    positions[wallet.address] = {
      x: center.x + Math.cos(angle) * radius,
      y: center.y + Math.sin(angle) * radius,
    };
  });
  return positions;
}

export default function WalletGraph({ wallets, edges }) {
  const [hover, setHover] = useState(null);
  const W = 720;
  const H = 360;
  const positions = useMemo(() => layout(wallets || [], W, H), [wallets]);

  if (!wallets?.length) {
    return (
      <div className="panel p-4 h-[400px] grid place-items-center text-zinc-500 text-[12px]">
        Loading wallet intelligence…
      </div>
    );
  }

  const hovered = wallets.find((w) => w.address === hover);

  return (
    <div className="panel p-0 overflow-hidden">
      <div className="px-3 py-2 flex items-center justify-between border-b border-ink-700/60">
        <div className="flex items-center gap-2">
          <span className="label-mono">Wallet intelligence</span>
          <span className="chip-purple">{wallets.length} nodes</span>
          <span className="chip-zinc">{edges?.length || 0} edges</span>
        </div>
        <div className="flex gap-1.5 text-[9px] uppercase tracking-widest">
          {Object.entries(CLUSTER_COLORS).map(([k, c]) => (
            <span key={k} className="flex items-center gap-1 text-zinc-500">
              <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: c, boxShadow: `0 0 6px ${c}` }} />
              {k}
            </span>
          ))}
        </div>
      </div>

      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[360px] block">
          <defs>
            <radialGradient id="bgGlow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#0d1117" />
              <stop offset="100%" stopColor="#05070a" />
            </radialGradient>
            {Object.entries(CLUSTER_COLORS).map(([k, c]) => (
              <radialGradient key={k} id={`glow-${k}`} cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor={c} stopOpacity="0.9" />
                <stop offset="60%" stopColor={c} stopOpacity="0.15" />
                <stop offset="100%" stopColor={c} stopOpacity="0" />
              </radialGradient>
            ))}
          </defs>
          <rect width={W} height={H} fill="url(#bgGlow)" />

          {/* Subtle grid */}
          <g opacity="0.25">
            {Array.from({ length: 12 }).map((_, i) => (
              <line key={`vx${i}`} x1={(i * W) / 12} y1={0} x2={(i * W) / 12} y2={H} stroke="#11161d" strokeWidth="1" />
            ))}
            {Array.from({ length: 6 }).map((_, i) => (
              <line key={`hy${i}`} x1={0} y1={(i * H) / 6} x2={W} y2={(i * H) / 6} stroke="#11161d" strokeWidth="1" />
            ))}
          </g>

          {/* Edges */}
          {(edges || []).map((e, i) => {
            const a = positions[e.from];
            const b = positions[e.to];
            if (!a || !b) return null;
            const isHover = hover && (e.from === hover || e.to === hover);
            return (
              <line
                key={i}
                x1={a.x} y1={a.y}
                x2={b.x} y2={b.y}
                stroke={isHover ? "#00ff9c" : "#1f2733"}
                strokeOpacity={isHover ? 0.55 : 0.45}
                strokeWidth={Math.max(0.6, e.weight * 1.6)}
              />
            );
          })}

          {/* Nodes */}
          {wallets.map((w) => {
            const p = positions[w.address];
            const c = CLUSTER_COLORS[w.cluster] || "#52606d";
            const r = 8 + (w.skill_score / 100) * 10;
            const isHover = hover === w.address;
            return (
              <g
                key={w.address}
                transform={`translate(${p.x}, ${p.y})`}
                onMouseEnter={() => setHover(w.address)}
                onMouseLeave={() => setHover(null)}
                style={{ cursor: "pointer" }}
              >
                <circle r={r * 2.4} fill={`url(#glow-${w.cluster})`} opacity={isHover ? 0.9 : 0.6} />
                <circle r={r} fill="#05070a" stroke={c} strokeWidth={isHover ? 2 : 1.4} />
                <circle r={r * 0.45} fill={c} opacity={0.85} />
                <text
                  y={r + 12}
                  textAnchor="middle"
                  fontSize="9"
                  fontFamily="JetBrains Mono"
                  fill={isHover ? "#e5e7eb" : "#7b8794"}
                  style={{ pointerEvents: "none" }}
                >
                  {w.label}
                </text>
              </g>
            );
          })}
        </svg>

        {/* Hover detail */}
        <div
          className={cls(
            "absolute left-3 bottom-3 right-3 md:right-auto md:max-w-[340px] panel p-3 transition-all duration-150",
            hovered ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2 pointer-events-none"
          )}
        >
          {hovered && (
            <>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className="inline-block w-2 h-2 rounded-full"
                    style={{ background: CLUSTER_COLORS[hovered.cluster], boxShadow: `0 0 8px ${CLUSTER_COLORS[hovered.cluster]}` }}
                  />
                  <span className="display text-zinc-100 text-[13px] font-semibold">{hovered.label}</span>
                </div>
                <span className="chip-zinc">{hovered.cluster}</span>
              </div>
              <div className="text-[10px] text-zinc-500 mt-1 num">{shortAddr(hovered.address)}</div>
              <div className="grid grid-cols-3 gap-2 mt-2 text-[11px]">
                <div>
                  <div className="label-mono">Win rate</div>
                  <div className="num text-neon-green">{fmtPct(hovered.win_rate)}</div>
                </div>
                <div>
                  <div className="label-mono">ROI 30d</div>
                  <div className={cls("num", hovered.roi_30d >= 0 ? "text-neon-green" : "text-neon-red")}>
                    {fmtPct(hovered.roi_30d)}
                  </div>
                </div>
                <div>
                  <div className="label-mono">Skill</div>
                  <div className="num text-neon-yellow">{hovered.skill_score.toFixed(1)}</div>
                </div>
              </div>
              <div className="mt-1 text-[11px]">
                <span className="label-mono">Vol 30d</span>{" "}
                <span className="num text-zinc-200">{fmtUsd(hovered.volume_30d, 0)}</span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
