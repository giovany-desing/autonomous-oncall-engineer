"""
Deduplicación de incidentes vía fingerprinting determinístico + DynamoDB.
Antes de correr el pipeline completo de 4 agentes (con su costo de LLM),
se calcula un fingerprint del incidente y se intenta registrar de forma
atómica en DynamoDB. Si ya existe dentro de la ventana de deduplicación,
el incidente se descarta sin invocar el grafo.
"""
import hashlib
import time
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError

DEFAULT_DEDUP_WINDOW_MINUTES = 30
TABLE_NAME = "oncall-agent-incident-fingerprints"


@dataclass
class FingerprintCheckResult:
    fingerprint_id: str
    is_duplicate: bool


def _normalize_trigger_summary(trigger_summary: str) -> str:
    """
    Quita partes variables típicas de un mensaje de error (IDs, timestamps,
    números) para que dos ocurrencias del MISMO bug generen el mismo
    fingerprint, aunque el request ID o el timestamp cambien entre ellas.
    """
    import re
    text = trigger_summary.lower()
    text = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>", text)
    text = re.sub(r"\d{4}-\d{2}-\d{2}t[\d:.]+z?", "<timestamp>", text)
    text = re.sub(r"\b\d+\b", "<num>", text)
    return text.strip()


def compute_fingerprint(project_name: str, trigger_summary: str) -> str:
    normalized = _normalize_trigger_summary(trigger_summary)
    raw = f"{project_name}:{normalized}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def check_and_register_fingerprint(
    project_name: str,
    trigger_summary: str,
    region: str,
    dedup_window_minutes: int = DEFAULT_DEDUP_WINDOW_MINUTES,
    aws_client=None,
) -> FingerprintCheckResult:
    fingerprint_id = compute_fingerprint(project_name, trigger_summary)
    table = (aws_client or boto3.resource("dynamodb", region_name=region)).Table(TABLE_NAME)

    expires_at = int(time.time()) + (dedup_window_minutes * 60)

    try:
        table.put_item(
            Item={
                "fingerprint_id": fingerprint_id,
                "project_name": project_name,
                "trigger_summary": trigger_summary,
                "expires_at": expires_at,
            },
            ConditionExpression="attribute_not_exists(fingerprint_id)",
        )
        return FingerprintCheckResult(fingerprint_id=fingerprint_id, is_duplicate=False)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return FingerprintCheckResult(fingerprint_id=fingerprint_id, is_duplicate=True)
        raise


if __name__ == "__main__":
    import sys

    project_name = sys.argv[1] if len(sys.argv) > 1 else "rag-demo"
    trigger_summary = sys.argv[2] if len(sys.argv) > 2 else "Error en process_upload al parsear JSON"
    region = sys.argv[3] if len(sys.argv) > 3 else "us-east-1"

    print("=== Primer intento (debe ser nuevo) ===")
    result1 = check_and_register_fingerprint(project_name, trigger_summary, region)
    print(f"Fingerprint: {result1.fingerprint_id}")
    print(f"Es duplicado: {result1.is_duplicate}")

    print("\n=== Segundo intento, mismo incidente (debe ser duplicado) ===")
    result2 = check_and_register_fingerprint(project_name, trigger_summary, region)
    print(f"Fingerprint: {result2.fingerprint_id}")
    print(f"Es duplicado: {result2.is_duplicate}")

    print("\n=== Tercer intento, mismo tipo de error pero con un UUID distinto en el mensaje ===")
    trigger_summary_variant = trigger_summary + " RequestId: 71bb2d50-917d-43f3-a2e2-7eeb49c22b45"
    result3 = check_and_register_fingerprint(project_name, trigger_summary_variant, region)
    print(f"Fingerprint: {result3.fingerprint_id}")
    print(f"Es duplicado: {result3.is_duplicate}")
    print("(esperado: True, porque el UUID se normaliza y el fingerprint base es el mismo)")
