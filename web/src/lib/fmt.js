export const fmtPct = (n, digits = 2) =>
  n === null || n === undefined ? "—" : `${(n * 100).toFixed(digits)}%`;

export const fmtUsd = (n, digits = 2) =>
  n === null || n === undefined
    ? "—"
    : `$${Number(n).toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })}`;

export const fmtNum = (n, digits = 0) =>
  n === null || n === undefined
    ? "—"
    : Number(n).toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });

export const shortAddr = (a) =>
  !a ? "—" : `${a.slice(0, 6)}…${a.slice(-4)}`;

export const cls = (...xs) => xs.filter(Boolean).join(" ");
