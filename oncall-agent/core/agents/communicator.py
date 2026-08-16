"""
Nodo Comunicador del grafo de LangGraph. Formatea el resultado final del
diagnóstico y lo envía a Slack vía Bot Token (chat.postMessage, no
webhook) -- necesario para capturar el thread_ts y poder sostener una
conversación de seguimiento en el mismo hilo. Guarda el estado completo
del incidente en DynamoDB, indexado por thread_ts, para que preguntas
futuras en el hilo puedan recuperar la evidencia real usada.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import boto3
import requests
from dotenv import load_dotenv

from core.config import ProjectConfig
from core.state import DiagnosisState

load_dotenv()

GROQ_PRICE_PER_MILLION_TOKENS = {
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
}
BEDROCK_PRICE_PER_MILLION_TOKENS = {
    "anthropic.claude-sonnet-5": {"input": 3.00, "output": 15.00},
}

SLACK_CHANNEL = "todo-oncall-agent-dev"
CONTEXT_TABLE_NAME = "oncall-agent-incident-context"
CONTEXT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 dias


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
        "",
        "_Responde en este hilo si tienes preguntas sobre el diagnostico._",
    ]
    return "\n".join(lines)


def _post_to_slack(message: str) -> dict:
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    if not bot_token:
        return {"ok": False, "error": "SLACK_BOT_TOKEN no configurado"}

    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"channel": SLACK_CHANNEL, "text": message},
    )
    return response.json()


def _save_incident_context(thread_ts: str, state: DiagnosisState, region: str) -> None:
    table = boto3.resource("dynamodb", region_name=region).Table(CONTEXT_TABLE_NAME)
    table.put_item(
        Item={
            "thread_ts": thread_ts,
            "incident_id": state.get("incident_id", ""),
            "project_name": state.get("project_name", ""),
            "manifest_path": state.get("manifest_path", ""),
            "validated_hypothesis": json.dumps(state.get("validated_hypothesis") or {}),
            "confidence_level": state.get("confidence_level", ""),
            "candidate_functions": json.dumps(state.get("candidate_functions", [])),
            "log_events": json.dumps(state.get("log_events", [])[-20:]),
            "similar_postmortems": json.dumps(state.get("similar_postmortems", [])),
            "expires_at": int(time.time()) + CONTEXT_TTL_SECONDS,
        }
    )


def communicator_node(state: DiagnosisState, config: ProjectConfig, send: bool = True) -> DiagnosisState:
    message = _format_message(state)
    notification_sent = False
    thread_ts = None

    if send:
        slack_response = _post_to_slack(message)
        notification_sent = slack_response.get("ok", False)
        thread_ts = slack_response.get("ts")

        if notification_sent and thread_ts:
            try:
                _save_incident_context(thread_ts, state, config.aws_region)
            except Exception as e:
                print(f"ADVERTENCIA: no se pudo guardar el contexto del incidente: {e}")

    return {
        "final_message": message,
        "notification_sent": notification_sent,
        "slack_thread_ts": thread_ts,
    }


if __name__ == "__main__":
    from core.config import load_project_config
    from core.agents.collector import collector_node
    from core.agents.hypothesis import hypothesis_node
    from core.agents.validator import validator_node

    config = load_project_config("manifests/rag-demo.yaml")
    initial_state: DiagnosisState = {
        "incident_id": "test-manual-bot-token",
        "project_name": config.name,
        "manifest_path": "manifests/rag-demo.yaml",
        "trigger_source": "manual_test",
        "trigger_summary": "",
    }

    state = {**initial_state, **collector_node(initial_state, config)}
    state = {**state, **hypothesis_node(state, config)}
    state = {**state, **validator_node(state, config)}

    result = communicator_node(state, config, send=True)
    print(result["final_message"])
    print()
    print(f"Notificacion enviada: {result['notification_sent']}")
    print(f"Thread ts: {result['slack_thread_ts']}")
