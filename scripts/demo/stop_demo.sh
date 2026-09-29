#!/usr/bin/env bash
# Stops everything started by run_demo.sh (direct-run PIDs + notifier/moto containers).
# Redis is left running (it pre-existed the demo and is shared).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PIDS="$ROOT/scripts/demo/pids"

for pf in "$PIDS"/*.pid; do
  [ -f "$pf" ] || continue
  pid="$(cat "$pf" 2>/dev/null)"
  [ -n "$pid" ] || continue
  kill -TERM -- -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  echo "stopped $(basename "$pf" .pid) (pid $pid)"
done
rm -rf "$PIDS"

docker compose -f "$ROOT/docker-compose.yml" --profile local-aws stop notifier moto 2>/dev/null || true
echo "demo stopped (redis left running; docker log-generator/detector untouched)"
