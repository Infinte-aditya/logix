# Project State
Last updated: 2026-09-30 by Aditya

## What works right now (verified)
- No version conflicts across 4 Python services + frontend (redis==8.1.0, pytest==9.1.1, ruff==0.16.9 consistent everywhere)
- Detector tests: 40/40 passed
- Notifier tests: 13/13 passed
- Gateway tests: 12/12 passed
- Log-generator tests: 2/2 passed
- Frontend tests: 11/11 passed + production build succeeds
- Redis reachable (PONG)
- GET /settings returns defaults matching schema
- PUT /settings accepted & persisted to Redis; changes survive restart
- Detector picks up settings changes live (polls Redis every 10s; threshold changes reflected immediately)
- Full alert flow: log-generator -> detector -> Redis alerts channel -> gateway -> frontend (WebSocket) confirmed
- Notifier delivers to moto (local AWS mock), not real AWS; delivery log confirmed "sent" entries
- Gateway health endpoint reports redis status + client count
- POST /notifications/test publishes a valid test alert to the pipeline
- Frontend serves at :8080, gateway API at :8001

## What's partially done
- alerts:history Redis list + GET /alerts endpoint — skipped, timebox exceeded (docs/SKIPPED.md #2f)
- Frontend "Notification log" tab — notifier delivery endpoint exists but UI tab deferred (docs/SKIPPED.md #3e)
- "Send test alert" button in UI — POST /notifications/test endpoint exists but button deferred (docs/SKIPPED.md #3g)

## What's broken / known issues
- /stats endpoint always returns zeros (services/gateway/app/main.py:190) — see BACKLOG.md item 1
- moto is profile-gated (local-aws) and not started by default — see BACKLOG.md item 2

## Next task (single item, the ONLY thing the next session should attempt)
- Fix /stats endpoint always returning zeros (BACKLOG.md item 1) — small, well-scoped, good first daily-session task

## Backlog
- See docs/progress/BACKLOG.md for the full ordered list