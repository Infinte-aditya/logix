# log-anomaly-detector

Real-time log anomaly detection system: a generator writes logs to a shared file, a detector watches error rates per window and publishes alerts to a Redis pub/sub channel, a gateway streams those alerts to a browser frontend over WebSocket, and a notifier fans them out to AWS SNS. For agent rules, contracts, and hard constraints, see AGENTS.md.
