// Lightweight fetch wrapper. The Vite dev server proxies /api → backend.
// In Docker, the frontend container also proxies /api via env target.
const json = async (res) => {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json();
};

const qp = (platform) => (platform ? `platform=${encodeURIComponent(platform)}` : "");

export const api = {
  health: () => fetch("/api/health").then(json),
  status: () => fetch("/api/status").then(json),
  platforms: () => fetch("/api/platforms").then(json),
  markets: (platform) => fetch(`/api/markets?${qp(platform)}`).then(json),
  orderbook: (id, platform) =>
    fetch(`/api/orderbook?market_id=${encodeURIComponent(id)}&${qp(platform)}`).then(json),
  scan: (platform) => fetch(`/api/scan?${qp(platform)}`).then(json),
  wallets: () => fetch("/api/wallets").then(json),
  risk: () => fetch("/api/risk").then(json),
  kill: () => fetch("/api/kill", { method: "POST" }).then(json),
  unkill: () => fetch("/api/unkill", { method: "POST" }).then(json),
  aiStatus: () => fetch("/api/ai/status").then(json),
  aiAnalyze: (payload) =>
    fetch("/api/ai/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    }).then(json),
};
