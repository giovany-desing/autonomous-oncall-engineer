"""
Handler de Lambda para la sonda sintética, disparado por EventBridge
Scheduler. Inyecta el fallo conocido, y si confirma el punto ciego,
dispara el pipeline de diagnóstico completo -- el mismo mecanismo que
usa el subscription filter, pero activado proactivamente en vez de
esperar una señal de error que sabemos que nunca va a llegar.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from probes.synthetic_probe import run_probe
from core.entrypoint import process_incident

BUCKET = "rag-demo-uploads-531728396479"
LOG_GROUP = "/aws/lambda/rag-demo-handler"
REGION = "us-east-1"
MANIFEST_PATH = "manifests/rag-demo-lambda.yaml"


def lambda_handler(event, context):
    result = run_probe(BUCKET, LOG_GROUP, REGION, wait_seconds=10)

    if not result.blind_spot_confirmed:
        return {
            "statusCode": 200,
            "body": json.dumps({
                "probe_id": result.probe_id,
                "blind_spot_confirmed": False,
                "message": "El sistema registro evidencia del fallo inyectado, no se dispara diagnostico.",
            }),
        }

    trigger_summary = (
        f"Sonda sintetica {result.probe_id}: se inyecto un payload JSON malformado "
        f"({result.injected_payload}) y no se encontro ninguna evidencia de error en "
        f"CloudWatch Logs tras 10 segundos. Punto ciego confirmado -- posible manejo "
        f"de excepciones silencioso en el flujo de carga de documentos."
    )

    diagnosis_result = process_incident(
        manifest_path=MANIFEST_PATH,
        incident_id=f"probe-{result.probe_id}",
        trigger_source="synthetic_probe",
        trigger_summary=trigger_summary,
        send_notifications=True,
    )

    return {
        "statusCode": 200,
        "body": json.dumps({
            "probe_id": result.probe_id,
            "blind_spot_confirmed": True,
            "diagnosis_processed": diagnosis_result["processed"],
        }),
    }
