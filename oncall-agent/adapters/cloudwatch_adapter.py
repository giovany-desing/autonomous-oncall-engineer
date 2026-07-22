"""
Adaptador de CloudWatch Logs. Trae logs de un log group en una ventana de
tiempo específica alrededor de un incidente, usando consulta estructurada
(no búsqueda semántica) — código e infraestructura tienen identidad exacta.
"""
import time
from dataclasses import dataclass, field

import boto3


@dataclass
class LogEvent:
    timestamp_ms: int
    message: str
    log_stream: str


@dataclass
class LogFetchResult:
    log_group: str
    events: list = field(default_factory=list)
    has_explicit_error: bool = False
    request_ids: set = field(default_factory=set)


ERROR_MARKERS = ("ERROR", "Traceback", "Exception", "Task timed out")


def fetch_recent_logs(
    log_group: str,
    region: str,
    minutes_back: int = 5,
    aws_client=None,
) -> LogFetchResult:
    client = aws_client or boto3.client("logs", region_name=region)

    end_time_ms = int(time.time() * 1000)
    start_time_ms = end_time_ms - (minutes_back * 60 * 1000)

    events = []
    request_ids = set()
    next_token = None

    while True:
        kwargs = {
            "logGroupName": log_group,
            "startTime": start_time_ms,
            "endTime": end_time_ms,
            "limit": 500,
        }
        if next_token:
            kwargs["nextToken"] = next_token

        response = client.filter_log_events(**kwargs)

        for event in response.get("events", []):
            message = event["message"]
            events.append(LogEvent(
                timestamp_ms=event["timestamp"],
                message=message,
                log_stream=event["logStreamName"],
            ))
            if "RequestId:" in message:
                for part in message.split():
                    if part not in ("RequestId:",) and len(part) == 36 and part.count("-") == 4:
                        request_ids.add(part)

        next_token = response.get("nextToken")
        if not next_token:
            break

    has_error = any(
        marker in e.message for e in events for marker in ERROR_MARKERS
    )

    return LogFetchResult(
        log_group=log_group,
        events=events,
        has_explicit_error=has_error,
        request_ids=request_ids,
    )


if __name__ == "__main__":
    import sys
    import json

    log_group = sys.argv[1] if len(sys.argv) > 1 else "/aws/lambda/rag-demo-handler"
    region = sys.argv[2] if len(sys.argv) > 2 else "us-east-1"
    minutes = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    result = fetch_recent_logs(log_group, region, minutes_back=minutes)

    print(f"Log group: {result.log_group}")
    print(f"Eventos encontrados: {len(result.events)}")
    print(f"Tiene error explícito en logs: {result.has_explicit_error}")
    print(f"Request IDs detectados: {result.request_ids}")
    print()
    for e in result.events:
        print(f"  [{e.timestamp_ms}] {e.message.strip()}")
