"""
Nodo Hipótesis del grafo de LangGraph. Toma la evidencia reunida por el
Recolector y genera 2-3 hipótesis de causa raíz rankeadas vía Groq/Llama.
Escala a Bedrock (Claude) cuando el caso es ambiguo:
  - confianza de la hipótesis principal < 0.6, o
  - no hay evidencia de log explícita Y hay más de una función candidata
    de alto riesgo (ambigüedad real, no solo baja confianza autoreportada)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import boto3
from dotenv import load_dotenv
from groq import Groq

from core.config import ProjectConfig
from core.state import DiagnosisState

load_dotenv()

CONFIDENCE_ESCALATION_THRESHOLD = 0.6

SYSTEM_PROMPT = """Eres un ingeniero SRE senior generando hipótesis de \
causa raíz para un incidente de producción. Recibes evidencia estructurada: \
logs recientes, funciones de código candidatas (con su nivel de riesgo de \
manejo de errores y sus dependencias externas), recursos de infraestructura, \
y estadísticas de conexiones externas (latencia, errores).

Genera entre 1 y 3 hipótesis de causa raíz, rankeadas de más a menos \
probable. Sé honesto sobre la incertidumbre: si la evidencia es débil o \
ambigua, refleja eso en el campo "confianza" en vez de sonar seguro sin \
justificación.

Responde ÚNICAMENTE con un JSON válido (sin texto adicional, sin markdown) \
con esta forma exacta:
{
  "hypotheses": [
    {
      "causa_probable": "string breve, 1 línea",
      "explicacion": "string, 2-4 oraciones explicando el razonamiento",
      "solucion_propuesta": "string concreto y accionable, con archivo/línea si aplica",
      "confianza": 0.0 a 1.0
    }
  ]
}"""


def _build_user_prompt(state: DiagnosisState) -> str:
    return f"""Logs recientes ({len(state.get('log_events', []))} eventos, ¿hay error explícito?: {state.get('has_explicit_error')}):
{json.dumps(state.get('log_events', [])[-10:], indent=2, ensure_ascii=False)}

Funciones candidatas (por riesgo de manejo de errores):
{json.dumps(state.get('candidate_functions', []), indent=2, ensure_ascii=False)}

Config de la función Lambda:
{json.dumps(state.get('lambda_config'), indent=2, ensure_ascii=False)}

Estadísticas de conexiones externas (X-Ray):
{json.dumps(state.get('external_connection_stats', []), indent=2, ensure_ascii=False)}
"""


def _call_groq(system_prompt: str, user_prompt: str, model: str) -> tuple:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    content = json.loads(response.choices[0].message.content)
    usage = response.usage
    cost_entry = {
        "node": "hypothesis",
        "provider": "groq",
        "model": model,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
    }
    return content["hypotheses"], cost_entry


def _call_bedrock(system_prompt: str, user_prompt: str, model: str, region: str) -> tuple:
    client = boto3.client("bedrock-runtime", region_name=region)
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1500,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    })
    response = client.invoke_model(modelId=model, body=body)
    payload = json.loads(response["body"].read())
    text = payload["content"][0]["text"]
    content = json.loads(text)
    cost_entry = {
        "node": "hypothesis_escalated",
        "provider": "bedrock",
        "model": model,
        "prompt_tokens": payload["usage"]["input_tokens"],
        "completion_tokens": payload["usage"]["output_tokens"],
    }
    return content["hypotheses"], cost_entry


def _should_escalate(hypotheses: list, state: DiagnosisState) -> tuple:
    top_confidence = hypotheses[0]["confianza"] if hypotheses else 0.0
    if top_confidence < CONFIDENCE_ESCALATION_THRESHOLD:
        return True, f"confianza de la hipótesis principal ({top_confidence}) por debajo del umbral ({CONFIDENCE_ESCALATION_THRESHOLD})"

    high_risk_candidates = [
        fn for fn in state.get("candidate_functions", [])
        if any(b["risk"] == "alto" for b in fn.get("risk_blocks", []))
    ]
    if not state.get("has_explicit_error") and len(high_risk_candidates) > 1:
        return True, f"sin evidencia de log explícita y {len(high_risk_candidates)} funciones candidatas de alto riesgo"

    return False, ""


def hypothesis_node(state: DiagnosisState, config: ProjectConfig) -> DiagnosisState:
    user_prompt = _build_user_prompt(state)
    cost_breakdown = list(state.get("cost_breakdown", []))

    hypotheses, cost_entry = _call_groq(SYSTEM_PROMPT, user_prompt, config.hypothesis_model)
    hypotheses.sort(key=lambda h: h["confianza"], reverse=True)
    cost_breakdown.append(cost_entry)

    should_escalate, reason = _should_escalate(hypotheses, state)

    if should_escalate:
        escalated_hypotheses, escalation_cost = _call_bedrock(
            SYSTEM_PROMPT, user_prompt, config.escalation_model, config.escalation_region
        )
        escalated_hypotheses.sort(key=lambda h: h["confianza"], reverse=True)
        cost_breakdown.append(escalation_cost)

        return {
            "hypotheses": escalated_hypotheses,
            "escalated_to_bedrock": True,
            "escalation_reason": reason,
            "cost_breakdown": cost_breakdown,
        }

    return {
        "hypotheses": hypotheses,
        "escalated_to_bedrock": False,
        "escalation_reason": "",
        "cost_breakdown": cost_breakdown,
    }


if __name__ == "__main__":
    from core.config import load_project_config
    from core.agents.collector import collector_node

    config = load_project_config("manifests/rag-demo.yaml")
    initial_state: DiagnosisState = {
        "incident_id": "test-manual-002",
        "project_name": config.name,
        "trigger_source": "manual_test",
        "trigger_summary": "",
    }

    collected = collector_node(initial_state, config)
    merged_state = {**initial_state, **collected}

    result = hypothesis_node(merged_state, config)
    print(json.dumps(result, indent=2, ensure_ascii=False))
