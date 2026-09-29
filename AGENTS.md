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

## Daily session rules (added for free-model, budget-limited work)
- Every session reads docs/progress/STATE.md FIRST, before touching any code.
- Every session attempts EXACTLY ONE task: the "Next task" in STATE.md, unless it is
  already done, in which case take the top item from BACKLOG.md.
- Self-tracked budget: count every tool call you make (bash, str_replace, create_file,
  view, etc.) starting from 1. Announce the running count after each tool call in your
  reasoning, e.g. "[budget: 7/25]". STOP new work at 25 tool calls in a session, or
  sooner if you judge you are close to a rate limit or context limit.
- When stopping (task done OR budget reached OR blocked): leave the repo in a working,
  committed state. Never leave half-written code uncommitted. If the task isn't
  finished, commit what compiles/passes tests and clearly mark the rest as TODO in
  STATE.md, not in half-finished code.
- Always write a daily log at docs/progress/daily/<YYYY-MM-DD>.md (append a numbered
  suffix like -2 if a second session happens same day) before ending the session.
- Always update docs/progress/STATE.md's "Next task" to the exact next step, even if
  that step is "resume where this session stopped, at file X line Y."
- Never start a second task in the same session, even if budget remains. One task,
  verified and committed, is the unit of progress.
- Never attempt a task estimated to need more than ~25 tool calls. If BACKLOG.md's
  next item looks larger, break it into 2-3 smaller items in BACKLOG.md first, then
  do only the first piece.
