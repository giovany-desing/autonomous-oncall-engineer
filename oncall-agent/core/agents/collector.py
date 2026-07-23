"""
Nodo Recolector del grafo de LangGraph. Orquesta los 4 adaptadores para
reunir toda la evidencia disponible de un incidente antes de generar
cualquier hipótesis. No usa LLM — es determinístico y barato.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adapters.cloudwatch_adapter import fetch_recent_logs
from adapters.code_adapter import load_knowledge_base, find_function, find_functions_by_risk
from adapters.aws_resource_adapter import discover_resources_by_tag, get_lambda_config
from adapters.external_connection_adapter import fetch_external_connection_stats
from core.config import ProjectConfig
from core.state import DiagnosisState


def collector_node(state: DiagnosisState, config: ProjectConfig) -> DiagnosisState:
    updates: DiagnosisState = {}

    # 1. Logs de CloudWatch en la ventana del incidente
    log_group = config.log_groups[0] if config.log_groups else None
    if log_group:
        log_result = fetch_recent_logs(log_group, config.aws_region, minutes_back=10)
        updates["log_events"] = [
            {"timestamp_ms": e.timestamp_ms, "message": e.message} for e in log_result.events
        ]
        updates["has_explicit_error"] = log_result.has_explicit_error
        updates["request_ids"] = list(log_result.request_ids)
    else:
        updates["log_events"] = []
        updates["has_explicit_error"] = False
        updates["request_ids"] = []

    # 2. Código: si el trigger menciona una función específica, búsqueda directa;
    #    si no, traemos las funciones de mayor riesgo como candidatas.
    knowledge_base = load_knowledge_base(config.knowledge_base_path)
    trigger_summary = state.get("trigger_summary", "")

    candidate_results = []
    mentioned_function = None
    for fn in knowledge_base.get("funciones", []):
        if fn["name"] in trigger_summary:
            mentioned_function = fn["name"]
            break

    if mentioned_function:
        result = find_function(knowledge_base, mentioned_function)
        candidate_results = [result]
    else:
        candidate_results = find_functions_by_risk(knowledge_base, risk="alto")

    updates["candidate_functions"] = [
        {
            "name": r.name,
            "file": r.file,
            "line_start": r.line_start,
            "line_end": r.line_end,
            "external_calls": r.external_calls,
            "risk_blocks": r.risk_blocks,
        }
        for r in candidate_results if r.found
    ]

    # 3. Recursos de infraestructura por tag
    resources = discover_resources_by_tag(
        config.resource_tag_key, config.resource_tag_value, config.aws_region
    )
    updates["tagged_resources"] = [
        {"arn": r.arn, "resource_type": r.resource_type, "tags": r.tags} for r in resources
    ]

    lambda_resources = [r for r in resources if r.resource_type == "lambda"]
    if lambda_resources:
        function_name = lambda_resources[0].arn.split(":")[-1]
        lambda_config = get_lambda_config(function_name, config.aws_region)
        updates["lambda_config"] = lambda_config.__dict__

        # 4. Conexiones externas vía X-Ray, para esa misma función
        conn_report = fetch_external_connection_stats(function_name, config.aws_region, minutes_back=15)
        updates["external_connection_stats"] = [seg.__dict__ for seg in conn_report.segments]
    else:
        updates["lambda_config"] = None
        updates["external_connection_stats"] = []

    return updates


if __name__ == "__main__":
    from core.config import load_project_config

    config = load_project_config("manifests/rag-demo.yaml")
    initial_state: DiagnosisState = {
        "incident_id": "test-manual-001",
        "project_name": config.name,
        "trigger_source": "manual_test",
        "trigger_summary": "",
    }

    result = collector_node(initial_state, config)

    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))
