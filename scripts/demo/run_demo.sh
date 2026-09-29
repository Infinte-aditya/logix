#!/usr/bin/env bash
# One-command demo launcher. Starts every component that worked in verification.
# All components run REAL service code (no fallback stubs needed).
# Gateway uses port 8001 because port 8000 is taken by an unrelated app on this machine.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOGS="$ROOT/scripts/demo/logs"
PIDS="$ROOT/scripts/demo/pids"
GW_PORT="${GW_PORT:-8001}"
export VITE_WS_URL="ws://localhost:${GW_PORT}/ws"

mkdir -p "$LOGS" /tmp/demo
rm -rf "$PIDS"; mkdir -p "$PIDS"
: > /tmp/demo/app.log

start_bg() { # name, workdir, logfile, command...
  # setsid detaches the service (survives terminal close); sh writes its own PID
  # then execs the command, so the pidfile holds the real, killable service PID.
  local name="$1" dir="$2" log="$3"; shift 3
  (cd "$dir" && set -a && . "$ROOT/.env" && set +a && \
   setsid nohup sh -c 'echo $$ > "$1"; shift; exec "$@"' run "$PIDS/$name.pid" "$@" \
   > "$log" 2>&1 < /dev/null &)
  sleep 0.5
  echo "started $name (pid $(cat "$PIDS/$name.pid" 2>/dev/null || echo '?'))"
}

echo "== redis + moto (docker) =="
docker compose -f "$ROOT/docker-compose.yml" --profile local-aws up -d redis moto
for _ in $(seq 1 30); do
  docker exec logix-redis-1 redis-cli ping 2>/dev/null | grep -q PONG && break
  sleep 1
done
docker exec logix-redis-1 redis-cli ping | grep -q PONG || { echo "redis not ready"; exit 1; }

echo "== SNS topic on moto (fake credentials only) =="
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test "$ROOT/services/notifier/.venv/bin/python" - <<'EOF'
import boto3
sns = boto3.client("sns", region_name="us-east-1", endpoint_url="http://localhost:5000",
                   aws_access_key_id="test", aws_secret_access_key="test")
arn = sns.create_topic(Name="logix-alerts")["TopicArn"]
subs = [s["Endpoint"] for s in sns.list_subscriptions_by_topic(TopicArn=arn)["Subscriptions"]]
if "judge@example.com" not in subs:
    sns.subscribe(TopicArn=arn, Protocol="email", Endpoint="judge@example.com")
print("topic ready:", arn)
EOF

echo "== notifier (docker, real code) =="
docker compose -f "$ROOT/docker-compose.yml" --profile local-aws up -d notifier

echo "== log-generator, detector, gateway, frontend (direct, real code) =="
start_bg log-generator "$ROOT/services/log-generator" "$LOGS/log-generator.log" \
  "$ROOT/services/log-generator/.venv/bin/python" -m app.main
start_bg detector "$ROOT/services/detector" "$LOGS/detector.log" \
  "$ROOT/services/detector/.venv/bin/python" -m app.main
start_bg gateway "$ROOT/services/gateway" "$LOGS/gateway.log" \
  "$ROOT/services/gateway/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port "$GW_PORT"
start_bg frontend "$ROOT/services/frontend" "$LOGS/frontend.log" \
  env VITE_WS_URL="$VITE_WS_URL" npm run dev -- --host

echo
echo "Demo URLs (first alerts ~30-60s after start):"
echo "  frontend:  http://localhost:5173"
echo "  gateway:   http://localhost:${GW_PORT}/health  (ws: ${VITE_WS_URL})"
echo "  notifier:  docker logs logix-notifier-1 (SNS on moto :5000)"
echo "  logs:      $LOGS/ ; stop with scripts/demo/stop_demo.sh"
