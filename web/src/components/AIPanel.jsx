import { useState } from "react";
import { api } from "../lib/api";
import { cls } from "../lib/fmt";

export default function AIPanel({ aiStatus, market }) {
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const enabled = !!aiStatus?.enabled;

  const submit = async () => {
    setLoading(true);
    setResult(null);
    try {
      const data = await api.aiAnalyze({
        market_id: market?.id,
        question: q || null,
      });
      setResult(data);
    } catch (e) {
      setResult({
        enabled: enabled,
        analysis: null,
        message: `Request failed: ${e.message}. Dashboard remains in demo mode.`,
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={cls("panel p-4 relative overflow-hidden", enabled && "panel-glow")}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="label-mono">AI Analyst</span>
          {enabled ? (
            <span className="chip-green">ENABLED</span>
          ) : (
            <span className="chip-zinc">DISABLED</span>
          )}
        </div>
        <span className="text-[10px] text-zinc-500 tracking-widest">
          {aiStatus?.provider ? `via ${aiStatus.provider}` : "no provider"}
        </span>
      </div>

      {!enabled && (
        <div className="mt-3 p-4 rounded border border-dashed border-ink-700/80 bg-ink-850/60">
          <div className="display text-zinc-200 text-[14px] font-semibold">AI Analysis Disabled</div>
          <p className="text-[12px] text-zinc-400 mt-1 leading-relaxed">
            The dashboard is fully running in demo mode. To enable on-demand market
            analysis, add an API key to <span className="text-neon-green">.env</span>:
          </p>
          <pre className="mt-3 text-[11px] text-zinc-300 bg-ink-950 border border-ink-700/60 rounded p-2 overflow-x-auto">
{`# .env
ANTHROPIC_API_KEY=sk-ant-...
# or
OPENAI_API_KEY=sk-...`}
          </pre>
          <div className="mt-2 text-[10px] text-zinc-500">
            Restart the backend container to pick up the new key.
          </div>
        </div>
      )}

      {enabled && (
        <div className="mt-3 space-y-3">
          <div>
            <div className="label-mono mb-1">Ask the agent</div>
            <textarea
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={`e.g. analyze edge on "${market?.title || "selected market"}"`}
              rows={3}
              className="w-full bg-ink-950 border border-ink-700/80 rounded p-2.5 text-[12px] text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-neon-green/50 transition"
            />
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-[10px] text-zinc-500">
              Analysis is informational only. Not financial advice.
            </span>
            <button
              onClick={submit}
              disabled={loading}
              className="px-4 py-1.5 rounded border border-neon-green/40 bg-neon-green/10 text-neon-green text-[11px] uppercase tracking-widest hover:bg-neon-green/20 transition disabled:opacity-50"
            >
              {loading ? "analyzing…" : "analyze"}
            </button>
          </div>

          {result && (
            <div className="mt-2 p-3 rounded border border-ink-700/70 bg-ink-850/60">
              {result.analysis ? (
                <div className="text-[12px] text-zinc-200 whitespace-pre-wrap leading-relaxed">
                  {result.analysis}
                </div>
              ) : (
                <div className="text-[12px] text-zinc-400">{result.message}</div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
