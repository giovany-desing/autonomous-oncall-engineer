"""
Punto de entrada del sistema completo: fingerprinting -> grafo de diagnóstico.
Esta es la función que, en el siguiente bloque de trabajo, se empaqueta
como el handler real de la Lambda disparada por CloudWatch. Por ahora se
invoca manualmente para validar el filtro de costo end-to-end.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import load_project_config
from core.graph import run_diagnosis
from dedup.fingerprint import check_and_register_fingerprint


def process_incident(
    manifest_path: str,
    incident_id: str,
    trigger_source: str,
    trigger_summary: str,
    dedup_window_minutes: int = 30,
    send_notifications: bool = True,
) -> dict:
    config = load_project_config(manifest_path)

    fingerprint_result = check_and_register_fingerprint(
        project_name=config.name,
        trigger_summary=trigger_summary,
        region=config.aws_region,
        dedup_window_minutes=dedup_window_minutes,
    )

    if fingerprint_result.is_duplicate:
        return {
            "processed": False,
            "reason": "duplicate_fingerprint",
            "fingerprint_id": fingerprint_result.fingerprint_id,
        }

    diagnosis_result = run_diagnosis(
        config,
        incident_id=incident_id,
        trigger_source=trigger_source,
        trigger_summary=trigger_summary,
        send_notifications=send_notifications,
    )

    return {
        "processed": True,
        "fingerprint_id": fingerprint_result.fingerprint_id,
        "diagnosis": diagnosis_result,
    }


if __name__ == "__main__":
    print("=== Primer incidente (debe procesarse completo) ===")
    result1 = process_incident(
        manifest_path="manifests/rag-demo.yaml",
        incident_id="test-dedup-001",
        trigger_source="manual_test",
        trigger_summary="Error en process_upload al parsear JSON",
        send_notifications=False,
    )
    print(f"Procesado: {result1['processed']}")
    if result1["processed"]:
        print(f"Costo: {result1['diagnosis'].get('cost_breakdown')}")

    print("\n=== Segundo incidente, mismo bug (debe descartarse por dedup) ===")
    result2 = process_incident(
        manifest_path="manifests/rag-demo.yaml",
        incident_id="test-dedup-002",
        trigger_source="manual_test",
        trigger_summary="Error en process_upload al parsear JSON",
        send_notifications=False,
    )
    print(f"Procesado: {result2['processed']}")
    print(f"Razón: {result2.get('reason')}")
