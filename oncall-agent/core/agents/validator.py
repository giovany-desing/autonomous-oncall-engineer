"""
Nodo Validador del grafo de LangGraph. Cruza la hipótesis top generada
por el nodo Hipótesis contra postmortems similares (memoria RAG) y
calibra un nivel de confianza final honesto: "alta", "media", "baja", o
"insuficiente" si la evidencia no alcanza para afirmar nada útil.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from memory.postmortem_store import find_similar_postmortems
from core.config import ProjectConfig
from core.state import DiagnosisState

# Umbrales para calibrar el nivel de confianza final, combinando:
# - confianza autoreportada por el LLM en la hipótesis top
# - si hubo o no evidencia de log explícita
# - si hay postmortems similares que corroboren la hipótesis
CONFIDENCE_LABELS = ["insuficiente", "baja", "media", "alta"]


def _calibrate_confidence(
    top_hypothesis: dict,
    has_explicit_error: bool,
    similar_postmortems: list,
) -> str:
    llm_confidence = top_hypothesis.get("confianza", 0.0)
    has_corroboration = any(
        pm["similarity"] >= 0.5 for pm in similar_postmortems
    )

    if llm_confidence < 0.3 and not has_explicit_error and not has_corroboration:
        return "insuficiente"

    if llm_confidence >= 0.7 and (has_explicit_error or has_corroboration):
        return "alta"

    if llm_confidence >= 0.5:
        return "media"

    if has_corroboration:
        return "media"

    return "baja"


def validator_node(state: DiagnosisState, config: ProjectConfig) -> DiagnosisState:
    hypotheses = state.get("hypotheses", [])
    if not hypotheses:
        return {
            "validated_hypothesis": None,
            "confidence_level": "insuficiente",
            "similar_postmortems": [],
        }

    top_hypothesis = hypotheses[0]
    query_text = f"{top_hypothesis['causa_probable']}. {top_hypothesis['explicacion']}"

    similar_postmortems = find_similar_postmortems(
        config.postmortem_store_path,
        query_text,
        top_k=3,
        min_similarity=0.3,
    )

    confidence_level = _calibrate_confidence(
        top_hypothesis,
        state.get("has_explicit_error", False),
        similar_postmortems,
    )

    return {
        "validated_hypothesis": top_hypothesis,
        "confidence_level": confidence_level,
        "similar_postmortems": similar_postmortems,
    }


if __name__ == "__main__":
    import json
    from core.config import load_project_config
    from core.agents.collector import collector_node
    from core.agents.hypothesis import hypothesis_node

    config = load_project_config("manifests/rag-demo.yaml")
    initial_state: DiagnosisState = {
        "incident_id": "test-manual-003",
        "project_name": config.name,
        "trigger_source": "manual_test",
        "trigger_summary": "",
    }

    collected = collector_node(initial_state, config)
    state_after_collect = {**initial_state, **collected}

    hyp_result = hypothesis_node(state_after_collect, config)
    state_after_hypothesis = {**state_after_collect, **hyp_result}

    result = validator_node(state_after_hypothesis, config)
    print(json.dumps(result, indent=2, ensure_ascii=False))
