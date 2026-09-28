# AGENTS.md: rules for every AI agent in this repo

## Project
Real-time log anomaly detector. 5 services communicating over Redis pub/sub.
log-generator -> (shared file) -> detector -> Redis channel "alerts" -> gateway (WebSocket) -> frontend
                                                                    -> notifier -> AWS SNS

## The contract (do not change without human approval)
- Log line format: `<ISO8601 UTC> <LEVEL> <service> <message>`, LEVEL in INFO|WARN|ERROR
- Log file path inside containers: /data/app.log (Docker volume `logdata`)
- Redis channel: `alerts`. Message = JSON matching contracts/alert.schema.json
- Severity values: LOW | MEDIUM | HIGH | CRITICAL
- Ports: redis 6379, gateway 8000, frontend 8080
- Env vars: REDIS_URL, LOG_PATH, WINDOW_SECONDS, ALERT_CHANNEL, AWS_REGION,
  SNS_TOPIC_ARN, AWS_ENDPOINT_URL (optional, for LocalStack)

## Hard rules
1. Only edit files inside the folders your task names. Never touch another service's folder.
2. Never edit AGENTS.md or contracts/ unless the task says so. If the contract seems wrong, STOP and tell the human.
3. Never install anything globally, never use sudo, never modify system config.
4. Never commit secrets. No AWS keys in code, .env, Dockerfiles, or logs. Use env vars only.
   Only .env.example (placeholders) is committed.
5. Pin every dependency to an exact version. Python 3.11, Node 20.
6. No new services, databases, brokers, or frameworks beyond what the task lists.
7. Keep each service small: aim for under 200 lines of app code. No speculative features.
8. Every service must: read config from env vars, log to stdout, handle SIGTERM,
   and run via its own Dockerfile.
9. Never run destructive commands (rm -rf outside your service folder, git push --force,
   docker system prune, aws delete-*/terminate-*) without explicit human approval.
10. Never call real AWS unless the task says so. Default to LocalStack/moto.
11. Work on your own branch (feat/<name>-<service>). Never commit to main directly.

## Definition of done (every task)
- Runs with the stated command, tests pass, no lint errors
- You print a short summary: files changed, commands run, anything unverified
- If anything is ambiguous or blocked: stop and ask. Do not guess.
