# Security Policy

PolyAgent can, when explicitly configured, place real orders with real money
using real private keys. Security is therefore a first-class concern.

## Never commit secrets

- `.env` and `.env.*` are git-ignored (except `.env.example`). Keep it that way.
- **Never** commit a private key, API secret, passphrase, or funded address.
- `agent/config.py` is the single place secrets are read from the environment;
  nothing else should read `os.environ` for credentials.
- If you accidentally commit a secret, **rotate it immediately** — assume any
  key that ever touched a commit is compromised, even after a force-push.

## Safe-by-default guarantees

Contributions must preserve these invariants:

- The default mode is `PAPER_TRADING`. No code path may place a live order
  unless **all** of: `MODE=AUTO_TRADING`, `LIVE_TRADING_CONFIRMED` set to the
  exact phrase, API keys present, jurisdiction allowed, and the kill switch
  absent.
- The web layer (`agent/web/api.py`) must **never** initiate live trading.
- Touching `data/KILL_SWITCH` must halt all live activity.

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue.

- Use GitHub's **"Report a vulnerability"** (Security → Advisories) on this
  repository, or
- email the maintainer listed on the repository profile.

Include reproduction steps and impact. We aim to acknowledge within 72 hours
and will coordinate a fix and disclosure timeline with you.

## Supported versions

This is pre-1.0 software; only the latest `main` is supported. Pin a commit
if you need stability.
