# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Manifold Markets connector** (`agent/connectors/manifold.py`) — the agent
  now runs end-to-end against a real platform with **no keys and no cost**
  (Manifold's public API). Read-only; a documented, tested worked example for
  the pluggable connector architecture.
- **Connector registry** (`agent/connectors/registry.py`) with auto-discovery:
  decorate a `BaseConnector` with `@register("name")` and it is instantly
  available everywhere. `registry.available()` lists all platforms.
- **`--platform` CLI flag** on `run` and `scan-once`, e.g.
  `python -m agent.main scan-once --platform manifold`.
- Open-source project infrastructure: `LICENSE` (MIT), GitHub Actions CI
  (ruff + pytest matrix + web build), `CONTRIBUTING.md`, `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, issue/PR templates, Dependabot, pre-commit, `ROADMAP.md`,
  and `docs/adding-a-connector.md`.

### Changed
- Focused ruff lint gate (`E`, `F`, `I`) configured in `pyproject.toml`; the
  codebase is lint-clean under it.
- `pytest` configured with `asyncio_mode = "strict"`.
