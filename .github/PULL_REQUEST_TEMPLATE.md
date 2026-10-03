<!-- Thanks for contributing to PolyAgent! -->

## What does this PR do?

<!-- One or two sentences. Link the issue it closes: "Closes #123". -->

## Type

- [ ] New connector
- [ ] Bug fix
- [ ] Feature / enhancement
- [ ] Docs / chore

## Checklist

- [ ] `ruff check .` passes
- [ ] `pytest -q` passes
- [ ] New/changed logic has tests (connectors: **offline** tests with mocked HTTP)
- [ ] No secrets, keys, or real `.env` committed
- [ ] Safe-by-default preserved: no new path can place a live order outside the
      existing mode + compliance + kill-switch gates

## Notes for reviewers

<!-- Anything non-obvious: trade-offs, follow-ups, screenshots for UI changes. -->
