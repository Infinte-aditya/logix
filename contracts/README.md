# Alert contract

1. Every detector message published on the Redis channel `alerts` must be a single JSON object.
2. The object must validate against `alert.schema.json` (JSON Schema draft-07).
3. `id` is a UUID v4 string unique per alert.
4. `timestamp` is ISO8601, UTC (`Z` suffix), e.g. `2026-09-28T12:00:00Z`.
5. `severity` is exactly one of LOW, MEDIUM, HIGH, CRITICAL.
6. `error_rate`, `baseline_mean`, `baseline_std`, `z_score` are numbers (floats).
7. `window_seconds` is an integer, matching the detector's WINDOW_SECONDS env var.
8. `message` is a human-readable one-line summary; no newlines.
9. All nine fields are required; no extra properties allowed.
10. Do not change this contract without human approval (see AGENTS.md).
