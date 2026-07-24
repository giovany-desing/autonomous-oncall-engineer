"""
Nodo Comunicador del grafo de LangGraph. Formatea el resultado final del
diagnóstico (hipótesis validada, confianza, evidencia, costo) como un
mensaje para Slack, y lo envía vía webhook. No usa LLM — solo presenta
lo que los otros tres nodos ya produjeron, sin agregar interpretación nueva.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests

from core.config import ProjectConfig
from core.state import DiagnosisState

GROQ_PRICE_PER_MILLION_TOKENS = {
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
}
BEDROCK_PRICE_PER_MILLION_TOKENS = {
    "anthropic.claude-3-5-sonnet-20241022-v2:0": {"input": 3.00, "output": 15.00},
}


def _estimate_cost_usd(cost_breakdown: list) -> float:
    total = 0.0
    for entry in cost_breakdown:
        model = entry.get("model", "")
        prompt_tokens = entry.get("prompt_tokens", 0)
        completion_tokens = entry.get("completion_tokens", 0)

        pricing = (
            GROQ_PRICE_PER_MILLION_TOKENS.get(model)
            or BEDROCK_PRICE_PER_MILLION_TOKENS.get(model)
        )
        if not pricing:
            continue

        total += (prompt_tokens / 1_000_000) * pricing["input"]
        total += (completion_tokens / 1_000_000) * pricing["output"]

    return round(total, 6)


def _format_message(state: DiagnosisState) -> str:
    hypothesis = state.get("validated_hypothesis")
    confidence = state.get("confidence_level", "insuficiente")
    escalated = state.get("escalated_to_bedrock", False)
    cost_usd = _estimate_cost_usd(state.get("cost_breakdown", []))
    candidate_functions = state.get("candidate_functions", [])
    similar_postmortems = state.get("similar_postmortems", [])

    if confidence == "insuficiente" or hypothesis is None:
        body = (
            f"*Incidente {state.get('incident_id', 'desconocido')} - {state.get('project_name', '')}*\n\n"
            f"No hay evidencia suficiente para proponer una causa con confianza razonable. "
            f"Se recomienda revisión manual.\n\n"
            f"Funciones candidatas evaluadas: {len(candidate_functions)}\n"
            f"Costo de esta investigación: ${cost_usd:.4f} USD"
        )
        return body

    lines = [
        f"*Incidente {state.get('incident_id', 'desconocido')} - {state.get('project_name', '')}*",
        f"Confianza: *{confidence}*" + (" (escalado a Bedrock/Claude)" if escalated else ""),
        "",
        f"*Causa probable:* {hypothesis['causa_probable']}",
        f"{hypothesis['explicacion']}",
        "",
        f"*Solución propuesta:* {hypothesis['solucion_propuesta']}",
        "",
        f"*Evidencia:* {len(candidate_functions)} función(es) de código analizada(s), "
        f"{len(similar_postmortems)} postmortem(s) similar(es) encontrado(s)",
        f"*Costo de esta investigación:* ${cost_usd:.4f} USD",
    ]
    return "\n".join(lines)


def communicator_node(state: DiagnosisState, config: ProjectConfig, send: bool = True) -> DiagnosisState:
    message = _format_message(state)
    notification_sent = False

    if send:
        webhook_url = os.environ.get(config.notification_webhook_env_var)
        if webhook_url:
            response = requests.post(webhook_url, json={"text": message})
            notification_sent = response.status_code == 200
        else:
            notification_sent = False

    return {
        "final_message": message,
        "notification_sent": notification_sent,
    }


if __name__ == "__main__":
    from core.config import load_project_config
    from core.agents.collector import collector_node
    from core.agents.hypothesis import hypothesis_node
    from core.agents.validator import validator_node

    config = load_project_config("manifests/rag-demo.yaml")
    initial_state: DiagnosisState = {
        "incident_id": "test-manual-004",
        "project_name": config.name,
        "trigger_source": "manual_test",
        "trigger_summary": "",
    }

    state = {**initial_state, **collector_node(initial_state, config)}
    state = {**state, **hypothesis_node(state, config)}
    state = {**state, **validator_node(state, config)}

    result = communicator_node(state, config, send=False)
    print(result["final_message"])
    print()
    print(f"Notificación enviada: {result['notification_sent']}")
