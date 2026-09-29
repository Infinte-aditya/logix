# Backlog

Ordered by priority. Each item should be doable in one session (~25 tool calls or fewer).
Break down anything bigger before starting it.

1. Fix /stats endpoint always returning zeros — services/gateway/app/main.py:190.
   Stats dict is initialized but never incremented when alerts arrive. Fix: increment
   stats[severity] in run_subscriber, or pass it as a mutable reference. Under 10 lines.

2. Decide whether moto (local AWS mock) should start by default instead of being
   gated behind the `local-aws` compose profile. Currently the notifier silently can't
   reach it unless the profile is explicitly enabled during `docker compose up`.

3. Add alerts:history Redis list + GET /alerts endpoint (previously skipped, SKIPPED.md #2f)
   — maintain a bounded list of recent alerts in Redis, expose via GET /alerts. Small
   scope: gateway adds handler + redis.lpush/ltrim on each received alert.

4. Add "Notification log" tab to frontend (previously skipped, SKIPPED.md #3e)
   — fetch GET /notifications from gateway, render as a table with status badges.

5. Add "Send test alert" button to frontend (previously skipped, SKIPPED.md #3g)
   — call POST /notifications/test from the Settings or Alerts tab.

6. Evaluate whether frontend should show WS connection status indicator
   — e.g. green/yellow/red dot when WebSocket connects/disconnects/reconnects. Small,
   isolated UI change.

7. Settings PUT validation rejects partial payloads — consider making it support
   partial updates (like PATCH semantics) or document that all fields are required.
   Currently PUT requires every field; sending only changed fields returns 422.
