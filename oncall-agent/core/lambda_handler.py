"""
Handler real de la Lambda del agente. Se dispara vía CloudWatch Logs
Subscription Filter cuando aparece un log de ERROR/WARNING en el log
group de CUALQUIER proyecto registrado (ver core/registry.py) -- no
asume un único proyecto fijo, para poder escalar a monitorear varios
proyectos con la misma Lambda.

El evento de un subscription filter llega comprimido en base64 + gzip
dentro de event["awslogs"]["data"] -- hay que decodificarlo antes de
poder leer los log events reales.
"""
import base64
import gzip
import json
import uuid

from core.entrypoint import process_incident
from core.registry import resolve_manifest_for_log_group


def _decode_cloudwatch_event(event: dict) -> dict:
    compressed_payload = base64.b64decode(event["awslogs"]["data"])
    payload = json.loads(gzip.decompress(compressed_payload))
    return payload


def lambda_handler(event, context):
    payload = _decode_cloudwatch_event(event)

    log_group = payload.get("logGroup", "")
    manifest_path = resolve_manifest_for_log_group(log_group)

    log_events = payload.get("logEvents", [])
    trigger_summary = " | ".join(e["message"] for e in log_events)[:2000]

    incident_id = str(uuid.uuid4())

    result = process_incident(
        manifest_path=manifest_path,
        incident_id=incident_id,
        trigger_source="cloudwatch",
        trigger_summary=trigger_summary,
        send_notifications=True,
    )

    print(f"RESULTADO_DIAGNOSTICO: incident_id={incident_id} project={log_group} "
          f"processed={result['processed']} reason={result.get('reason')} "
          f"notification_sent={result.get('diagnosis', {}).get('notification_sent') if result['processed'] else 'N/A'}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "incident_id": incident_id,
            "project": log_group,
            "processed": result["processed"],
            "reason": result.get("reason"),
        }),
    }
