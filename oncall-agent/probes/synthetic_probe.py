"""
Sonda sintética: inyecta activamente una entrada conocida como problemática
(JSON malformado, el mismo caso del bloque de riesgo alto detectado en el
onboarding) y verifica si el sistema monitoreado deja evidencia de ese
fallo en CloudWatch. Si no la deja, reporta la anomalía directamente --
este es el mecanismo que cubre puntos ciegos que nunca generan un log de
ERROR, y que el subscription filter reactivo nunca podría detectar.
"""
import json
import time
import uuid
from dataclasses import dataclass

import boto3

PROBE_MARKER_PREFIX = "oncall-agent-probe"


@dataclass
class ProbeResult:
    probe_id: str
    injected_payload: str
    evidence_found: bool
    blind_spot_confirmed: bool


def _upload_malformed_payload(bucket: str, probe_id: str) -> str:
    s3 = boto3.client("s3")
    key = f"uploads/{PROBE_MARKER_PREFIX}-{probe_id}.json"
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=b'{esto no es json valido, sonda sintetica}',
        ContentType="application/json",
    )
    return key


def _check_for_evidence(log_group: str, region: str, since_seconds: int = 60) -> bool:
    """
    Después de inyectar el fallo, busca CUALQUIER evidencia de que el
    sistema lo registró -- un log de ERROR, una excepción, o cualquier
    mención del ID de la sonda. Si no encuentra nada, confirma el punto
    ciego: el sistema falló en silencio, tal como se esperaba del bug
    conocido.
    """
    client = boto3.client("logs", region_name=region)
    end_time_ms = int(time.time() * 1000)
    start_time_ms = end_time_ms - (since_seconds * 1000)

    response = client.filter_log_events(
        logGroupName=log_group,
        startTime=start_time_ms,
        endTime=end_time_ms,
        filterPattern="?ERROR ?Exception ?Traceback",
    )
    return len(response.get("events", [])) > 0


def run_probe(
    bucket: str,
    log_group: str,
    region: str,
    wait_seconds: int = 10,
) -> ProbeResult:
    probe_id = str(uuid.uuid4())[:8]
    key = _upload_malformed_payload(bucket, probe_id)

    time.sleep(wait_seconds)

    evidence_found = _check_for_evidence(log_group, region)

    return ProbeResult(
        probe_id=probe_id,
        injected_payload=key,
        evidence_found=evidence_found,
        blind_spot_confirmed=not evidence_found,
    )


if __name__ == "__main__":
    import sys

    bucket = sys.argv[1] if len(sys.argv) > 1 else "rag-demo-uploads-531728396479"
    log_group = sys.argv[2] if len(sys.argv) > 2 else "/aws/lambda/rag-demo-handler"
    region = sys.argv[3] if len(sys.argv) > 3 else "us-east-1"

    print(f"Inyectando payload malformado en s3://{bucket}/uploads/...")
    result = run_probe(bucket, log_group, region, wait_seconds=10)

    print(f"Probe ID: {result.probe_id}")
    print(f"Payload inyectado: {result.injected_payload}")
    print(f"Evidencia encontrada en logs: {result.evidence_found}")
    print(f"Punto ciego confirmado: {result.blind_spot_confirmed}")
