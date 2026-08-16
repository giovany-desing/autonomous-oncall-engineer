"""
Evaluacion del sistema contra el dataset de ground truth (casos reales
diagnosticados hoy, con causa raiz conocida de antemano). Mide, por
caso: si el archivo/funcion esperado aparece mencionado en el
diagnostico, y el nivel de confianza reportado -- una version simple
pero honesta de "¿acierta el sistema?", sin necesitar un juez humano
para cada corrida.
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import load_project_config
from core.graph import run_diagnosis

DATASET_PATH = Path(__file__).resolve().parent / "eval_dataset.json"


def _mentions_expected_file(diagnosis_state: dict, expected_file_contains: str) -> bool:
    hypothesis = diagnosis_state.get("validated_hypothesis") or {}
    text = json.dumps(hypothesis, ensure_ascii=False).lower()
    candidate_functions = json.dumps(diagnosis_state.get("candidate_functions", []), ensure_ascii=False).lower()
    combined = text + " " + candidate_functions
    return expected_file_contains.lower() in combined


def _mentions_expected_function(diagnosis_state: dict, expected_function: str) -> bool:
    if not expected_function:
        return True  # no aplica, no penaliza
    hypothesis = diagnosis_state.get("validated_hypothesis") or {}
    text = json.dumps(hypothesis, ensure_ascii=False).lower()
    candidate_functions = json.dumps(diagnosis_state.get("candidate_functions", []), ensure_ascii=False).lower()
    combined = text + " " + candidate_functions
    return expected_function.lower() in combined


def run_evaluation(dataset_path: Path = DATASET_PATH) -> list:
    with open(dataset_path) as f:
        cases = json.load(f)

    results = []
    for case in cases:
        config = load_project_config(case["manifest"])

        diagnosis_state = run_diagnosis(
            config,
            incident_id=f"eval-{uuid.uuid4().hex[:8]}",
            trigger_source="evaluation",
            trigger_summary=case["trigger_summary"],
            send_notifications=False,
        )

        file_match = _mentions_expected_file(diagnosis_state, case["expected_file_contains"])
        function_match = _mentions_expected_function(diagnosis_state, case.get("expected_function"))
        confidence = diagnosis_state.get("confidence_level", "insuficiente")
        cost = sum(
            0 for _ in []
        )  # placeholder, el costo real ya se calcula en communicator; aqui solo medimos precision

        results.append({
            "case_id": case["id"],
            "descripcion": case["descripcion"],
            "file_match": file_match,
            "function_match": function_match,
            "confidence": confidence,
            "acierto_completo": file_match and function_match,
        })

    return results


def print_report(results: list) -> None:
    print("=== Reporte de evaluacion ===\n")
    aciertos = 0
    for r in results:
        status = "✅ ACIERTO" if r["acierto_completo"] else "❌ FALLO"
        print(f"{status} [{r['case_id']}] confianza={r['confidence']}")
        print(f"  {r['descripcion']}")
        print(f"  archivo esperado mencionado: {r['file_match']}, funcion esperada mencionada: {r['function_match']}")
        print()
        if r["acierto_completo"]:
            aciertos += 1

    total = len(results)
    print(f"=== Resultado: {aciertos}/{total} aciertos ({100 * aciertos / total:.0f}%) ===")


if __name__ == "__main__":
    results = run_evaluation()
    print_report(results)
