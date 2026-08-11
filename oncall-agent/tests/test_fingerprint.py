"""
Tests para dedup/fingerprint.py -- la normalizacion de UUIDs/timestamps
es la pieza que ya revelo un bug real (colapsar incidentes distintos
que solo difieren en un numero, ver Paso 192 del proyecto).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dedup.fingerprint import compute_fingerprint, _normalize_trigger_summary


def test_mismo_bug_distinto_uuid_genera_mismo_fingerprint():
    msg_a = "Error en process_upload. RequestId: 71bb2d50-917d-43f3-a2e2-7eeb49c22b45"
    msg_b = "Error en process_upload. RequestId: 99aa1234-abcd-4444-8888-1234567890ab"

    fp_a = compute_fingerprint("rag-demo", msg_a)
    fp_b = compute_fingerprint("rag-demo", msg_b)

    assert fp_a == fp_b, "Mismo bug con distinto UUID deberia generar el mismo fingerprint"


def test_mismo_bug_distinto_timestamp_genera_mismo_fingerprint():
    msg_a = "Task timed out at 2026-07-28T00:12:16Z"
    msg_b = "Task timed out at 2026-07-28T00:45:33Z"

    fp_a = compute_fingerprint("moto-chatbot", msg_a)
    fp_b = compute_fingerprint("moto-chatbot", msg_b)

    assert fp_a == fp_b, "Mismo bug con distinto timestamp deberia generar el mismo fingerprint"


def test_proyectos_distintos_nunca_colisionan():
    same_message = "Error en process_upload al parsear JSON"

    fp_rag_demo = compute_fingerprint("rag-demo", same_message)
    fp_moto_chatbot = compute_fingerprint("moto-chatbot", same_message)

    assert fp_rag_demo != fp_moto_chatbot, "El mismo mensaje en proyectos distintos NUNCA debe colisionar"


def test_bugs_genuinamente_distintos_no_colisionan():
    msg_a = "ERROR: fallo de conexion a base de datos externa"
    msg_b = "ERROR: timeout al invocar servicio de pagos"

    fp_a = compute_fingerprint("moto-chatbot", msg_a)
    fp_b = compute_fingerprint("moto-chatbot", msg_b)

    assert fp_a != fp_b, "Bugs genuinamente distintos no deben colapsar al mismo fingerprint"


def test_normalizacion_reemplaza_uuid():
    text = "RequestId: 71bb2d50-917d-43f3-a2e2-7eeb49c22b45 fallo"
    normalized = _normalize_trigger_summary(text)
    assert "71bb2d50" not in normalized
    assert "<uuid>" in normalized
