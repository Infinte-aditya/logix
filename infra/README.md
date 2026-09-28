# Infra

AWS setup notes go here.

## Person B — notifier AWS setup (run these yourself; the agent never creates AWS resources)

All commands assume a configured AWS CLI profile (`aws configure` or env/role —
never hardcode credentials in the repo). Replace `<TOPIC_ARN>`, `<REGION>`,
`<ACCOUNT_ID>` after running each step.

### 1. SNS topic (provides `SNS_TOPIC_ARN`)

```bash
aws sns create-topic --name logix-alerts
# note the returned TopicArn -> SNS_TOPIC_ARN
```

### 2. Subscription (example: email; repeat per subscriber)

```bash
aws sns subscribe \
  --topic-arn <TOPIC_ARN> \
  --protocol email \
  --notification-endpoint ops@example.com
# confirm via the email AWS sends
```

### 3. CloudWatch Logs group (only if you set `CW_LOG_GROUP`)

```bash
aws logs create-log-group --group-name /logix/alerts
```

### 4. ECR repository for the notifier image

```bash
aws ecr create-repository --repository-name logix/notifier
aws ecr get-login-password --region <REGION> | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com
docker tag logix-notifier:latest <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/logix/notifier:latest
docker push <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/logix/notifier:latest
```

### 5. Minimal IAM policy for the notifier's task/instance role

```bash
aws iam create-policy --policy-name logix-notifier-publish --policy-document '{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublishAlerts",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "<TOPIC_ARN>"
    },
    {
      "Sid": "WriteAlertLogs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogStream", "logs:DescribeLogStreams", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:<REGION>:<ACCOUNT_ID>:log-group:/logix/alerts:*"
    }
  ]
}'
# attach the returned policy ARN to the role the notifier runs as
```

### 6. LocalStack (dev only — never point at real AWS for this task)

```bash
export AWS_ENDPOINT_URL=http://localhost:4566
export AWS_REGION=us-east-1
export SNS_TOPIC_ARN=arn:aws:sns:us-east-1:000000000000:logix-alerts
# LocalStack accepts placeholder credentials via the standard env chain:
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test
aws --endpoint-url "$AWS_ENDPOINT_URL" sns create-topic --name logix-alerts
```

Reminder (AGENTS.md rule 4): only `.env.example` with placeholders is ever
committed; real credentials live in your shell/role, never in files.
