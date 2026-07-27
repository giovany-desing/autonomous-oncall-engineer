"""
Handler de Lambda para la sonda sintética, disparado por EventBridge
Scheduler. Itera sobre TODOS los proyectos registrados (ver
core/registry.py) -- no asume un único proyecto fijo -- e inyecta el
fallo conocido de cada uno según lo declarado en su propio manifiesto.
Si confirma un punto ciego, dispara el pipeline de diagnóstico completo
para ese proyecto específico.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from probes.synthetic_probe import run_probe
from core.config import load_project_config
from core.entrypoint import process_incident
from core.registry import list_project_manifests

REGION = "us-east-1"


def _probe_project(manifest_path: Path) -> dict:
    config = load_project_config(manifest_path)

    if not config.probe_s3_bucket:
        return {
            "project": config.name,
            "skipped": True,
            "reason": "sin configuracion de sonda en el manifiesto",
        }

    log_group = config.log_groups[0] if config.log_groups else ""

    result = run_probe(
        bucket=config.probe_s3_bucket,
        log_group=log_group,
        region=config.aws_region,
        injected_payload=config.probe_injected_payload,
        key_prefix=config.probe_injected_key_prefix,
        wait_seconds=10,
    )

    if not result.blind_spot_confirmed:
        return {
            "project": config.name,
            "blind_spot_confirmed": False,
        }

    lambda_manifest_name = f"manifests/{manifest_path.stem}-lambda.yaml"
    trigger_summary = (
        f"Sonda sintetica {result.probe_id} en {config.name}: se inyecto un payload "
        f"conocido ({result.injected_payload}) y no se encontro ninguna evidencia de "
        f"error en CloudWatch Logs tras 10 segundos. Punto ciego confirmado."
    )

    diagnosis_result = process_incident(
        manifest_path=lambda_manifest_name,
        incident_id=f"probe-{result.probe_id}",
        trigger_source="synthetic_probe",
        trigger_summary=trigger_summary,
        send_notifications=True,
    )

    return {
        "project": config.name,
        "blind_spot_confirmed": True,
        "diagnosis_processed": diagnosis_result["processed"],
    }


def lambda_handler(event, context):
    results = []
    for manifest_path in list_project_manifests():
        results.append(_probe_project(manifest_path))

    return {
        "statusCode": 200,
        "body": json.dumps({"probes": results}),
    }
