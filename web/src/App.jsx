import { useEffect, useState, useCallback } from "react";
import { api } from "./lib/api";
import Header from "./components/Header";
import AgentCard from "./components/AgentCard";
import Chart from "./components/Chart";
import OrderBook from "./components/OrderBook";
import SignalPanel from "./components/SignalPanel";
import WalletGraph from "./components/WalletGraph";
import TradesTable from "./components/TradesTable";
import RiskPanel from "./components/RiskPanel";
import AIPanel from "./components/AIPanel";

export default function App() {
  const [status, setStatus] = useState(null);
  const [aiStatus, setAiStatus] = useState(null);
  const [markets, setMarkets] = useState([]);
  const [selected, setSelected] = useState(null);
  const [scan, setScan] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [wallets, setWallets] = useState({ wallets: [], edges: [] });
  const [risk, setRisk] = useState(null);
  const [bootError, setBootError] = useState(null);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await api.status();
      setStatus(s);
    } catch (e) {
      setBootError(e.message);
    }
  }, []);

  const refreshRisk = useCallback(async () => {
    try {
      setRisk(await api.risk());
    } catch (e) {
      console.error("risk:", e);
    }
  }, []);

  const runScan = useCallback(async () => {
    setScanning(true);
    try {
      setScan(await api.scan());
    } catch (e) {
      console.error("scan:", e);
    } finally {
      setScanning(false);
    }
  }, []);

  // Initial boot
  useEffect(() => {
    (async () => {
      try {
        const [s, ai, m, w, r, sc] = await Promise.all([
          api.status().catch(() => null),
          api.aiStatus().catch(() => ({ enabled: false, message: "AI status unavailable" })),
          api.markets().catch(() => ({ markets: [] })),
          api.wallets().catch(() => ({ wallets: [], edges: [] })),
          api.risk().catch(() => null),
          api.scan().catch(() => null),
        ]);
        setStatus(s);
        setAiStatus(ai);
        setMarkets(m.markets || []);
        setSelected((m.markets || [])[0] || null);
        setWallets(w);
        setRisk(r);
        setScan(sc);
      } catch (e) {
        setBootError(e.message || String(e));
      }
    })();
  }, []);

  // Periodic refresh — status, risk, market jitter
  useEffect(() => {
    const id = setInterval(async () => {
      refreshStatus();
      refreshRisk();
      try {
        const m = await api.markets();
        setMarkets(m.markets || []);
        setSelected((prev) => {
          if (!prev) return (m.markets || [])[0] || null;
          // Keep selection but update its data
          return (m.markets || []).find((x) => x.id === prev.id) || prev;
        });
      } catch (e) {
        // swallow — demo data should still render
      }
    }, 8000);
    return () => clearInterval(id);
  }, [refreshStatus, refreshRisk]);

  const onKill = async () => {
    try {
      await api.kill();
    } finally {
      refreshStatus();
      refreshRisk();
    }
  };
  const onUnkill = async () => {
    try {
      await api.unkill();
    } finally {
      refreshStatus();
      refreshRisk();
    }
  };

  return (
    <div className="relative z-10 min-h-screen flex flex-col">
      <Header status={status} />

      {bootError && (
        <div className="px-5 py-2 text-[11px] text-neon-red border-b border-neon-red/20 bg-neon-red/5">
          backend unreachable: {bootError} — showing cached/empty state
        </div>
      )}

      <main className="flex-1 px-5 py-4 grid grid-cols-12 gap-4">
        {/* Left column */}
        <div className="col-span-12 lg:col-span-3 flex flex-col gap-4">
          <AgentCard scan={scan} market={selected} />
          <SignalPanel scan={scan} onRescan={runScan} scanning={scanning} />
        </div>

        {/* Center column — chart + trades */}
        <div className="col-span-12 lg:col-span-6 flex flex-col gap-4">
          <Chart market={selected} markets={markets} onSelect={setSelected} />
          <WalletGraph wallets={wallets.wallets} edges={wallets.edges} />
          <TradesTable scan={scan} />
        </div>

        {/* Right column */}
        <div className="col-span-12 lg:col-span-3 flex flex-col gap-4">
          <OrderBook marketId={selected?.id || "mkt_001"} />
          <RiskPanel
            risk={risk}
            killed={status?.kill_switch}
            onKill={onKill}
            onUnkill={onUnkill}
          />
          <AIPanel aiStatus={aiStatus} market={selected} />
        </div>
      </main>

      <footer className="relative z-10 border-t border-ink-700/60 px-5 py-2 flex items-center justify-between text-[10px] uppercase tracking-[0.25em] text-zinc-500">
        <span>polyagent terminal · demo mode</span>
        <span className="flex items-center gap-3">
          <span>backend {status ? <span className="text-neon-green">online</span> : <span className="text-neon-red">offline</span>}</span>
          <span>·</span>
          <span>core {status?.core_loaded ? <span className="text-neon-green">loaded</span> : <span className="text-zinc-400">stub</span>}</span>
          <span>·</span>
          <span>not financial advice</span>
        </span>
      </footer>
    </div>
  );
}
