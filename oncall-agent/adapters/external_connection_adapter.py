"""
Adaptador de conexiones externas. Consulta AWS X-Ray para medir la
latencia y tasa de error observadas de las dependencias externas que
Tree-sitter detectó en el onboarding (s3.get_object, requests.post, etc.)
en la ventana de tiempo del incidente.

Importante sobre el alcance: este adaptador NUNCA intenta diagnosticar
qué pasó dentro del servicio externo — solo reporta lo que se observa
desde este lado de la llamada (latencia, si hubo error, throttling).
"""
import time
from dataclasses import dataclass, field

import boto3


@dataclass
class SegmentStats:
    name: str
    call_count: int = 0
    error_count: int = 0
    throttle_count: int = 0
    avg_duration_ms: float = 0.0
    max_duration_ms: float = 0.0


@dataclass
class ExternalConnectionReport:
    function_name: str
    window_minutes: int
    trace_count: int = 0
    segments: list = field(default_factory=list)


def _get_trace_ids(client, minutes_back: int, function_name: str) -> list:
    end_time = time.time()
    start_time = end_time - (minutes_back * 60)

    trace_ids = []
    paginator = client.get_paginator("get_trace_summaries")
    for page in paginator.paginate(
        StartTime=start_time,
        EndTime=end_time,
        FilterExpression=f'service("{function_name}")',
    ):
        for summary in page.get("TraceSummaries", []):
            trace_ids.append(summary["Id"])
    return trace_ids


def fetch_external_connection_stats(
    function_name: str,
    region: str,
    minutes_back: int = 10,
    aws_client=None,
) -> ExternalConnectionReport:
    client = aws_client or boto3.client("xray", region_name=region)

    trace_ids = _get_trace_ids(client, minutes_back, function_name)
    report = ExternalConnectionReport(
        function_name=function_name,
        window_minutes=minutes_back,
        trace_count=len(trace_ids),
    )

    if not trace_ids:
        return report

    stats_by_name = {}

    for i in range(0, len(trace_ids), 5):
        batch = trace_ids[i:i + 5]
        response = client.batch_get_traces(TraceIds=batch)

        for trace in response.get("Traces", []):
            for segment in trace.get("Segments", []):
                doc = segment.get("Document", "")
                import json as _json
                try:
                    parsed = _json.loads(doc)
                except _json.JSONDecodeError:
                    continue

                subsegments = parsed.get("subsegments", [])
                for sub in subsegments:
                    name = sub.get("name", "unknown")
                    if name not in stats_by_name:
                        stats_by_name[name] = SegmentStats(name=name)
                    stat = stats_by_name[name]
                    stat.call_count += 1
                    duration_ms = (sub.get("end_time", 0) - sub.get("start_time", 0)) * 1000
                    stat.avg_duration_ms = (
                        (stat.avg_duration_ms * (stat.call_count - 1) + duration_ms)
                        / stat.call_count
                    )
                    stat.max_duration_ms = max(stat.max_duration_ms, duration_ms)
                    if sub.get("error") or sub.get("fault"):
                        stat.error_count += 1
                    if sub.get("throttle"):
                        stat.throttle_count += 1

    report.segments = list(stats_by_name.values())
    return report


if __name__ == "__main__":
    import sys
    import json

    function_name = sys.argv[1] if len(sys.argv) > 1 else "rag-demo-handler"
    region = sys.argv[2] if len(sys.argv) > 2 else "us-east-1"
    minutes = int(sys.argv[3]) if len(sys.argv) > 3 else 15

    report = fetch_external_connection_stats(function_name, region, minutes_back=minutes)

    print(f"Función: {report.function_name}")
    print(f"Traces encontrados en los últimos {report.window_minutes} min: {report.trace_count}")
    print()
    for seg in report.segments:
        print(f"  Segmento: {seg.name}")
        print(f"    Llamadas: {seg.call_count} | Errores: {seg.error_count} | Throttles: {seg.throttle_count}")
        print(f"    Duración promedio: {seg.avg_duration_ms:.2f}ms | Máxima: {seg.max_duration_ms:.2f}ms")
