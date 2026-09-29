import boto3
import pytest
from app.main import SEVERITY_LEVEL, Notifier
from botocore.exceptions import ClientError
from moto import mock_aws

ALERT = {
    "id": "3f6b0d1e-6a3e-4f9a-9c6e-1a2b3c4d5e6f",
    "timestamp": "2026-09-28T12:00:00Z",
    "severity": "HIGH",
    "z_score": 12.33,
}


@pytest.fixture
def aws_env():
    """All AWS calls in tests run against moto; real AWS is never touched."""
    with mock_aws():
        yield


@pytest.fixture
def sns_and_topic(aws_env):
    sns = boto3.client("sns", region_name="us-east-1")
    topic_arn = sns.create_topic(Name="logix-alerts")["TopicArn"]
    return sns, topic_arn


@pytest.fixture
def queue(sns_and_topic):
    """An SQS queue subscribed to the topic, so published alerts are assertable."""
    sns, topic_arn = sns_and_topic
    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="notifier-test")["QueueUrl"]
    queue_arn = sqs.get_queue_attributes(
        QueueUrl=queue_url, AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]
    sns.subscribe(TopicArn=topic_arn, Protocol="sqs", Endpoint=queue_arn)
    return sqs, queue_url


@pytest.fixture
def notifier(sns_and_topic):
    sns, topic_arn = sns_and_topic
    return Notifier(
        sns=sns,
        topic_arn=topic_arn,
        min_severity=SEVERITY_LEVEL["MEDIUM"],
        retry_base_delay=0,
    )


def received_messages(sqs, queue_url):
    resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)
    return resp.get("Messages", [])


class FlakySNS:
    """Fake SNS client that raises ClientError for the first N calls."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def publish(self, **_kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise ClientError(
                {"Error": {"Code": "InternalError", "Message": "boom"}}, "Publish"
            )
