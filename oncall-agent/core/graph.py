"""
Ensambla los 4 agentes en un grafo de LangGraph. La secuencia es:
  Recolector -> Hipótesis -> Validador -> Comunicador

El nodo Hipótesis internamente decide si escala a Bedrock (ver
hypothesis.py, _should_escalate) — esa decisión ya queda reflejada en
el estado (escalated_to_bedrock) antes de llegar al Validador, así que
no necesita ser un edge condicional separado en el grafo: es parte de
la lógica interna del nodo Hipótesis, no una bifurcación de qué nodo
ejecutar después.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.graph import StateGraph, END

from core.config import ProjectConfig
from core.state import DiagnosisState
from core.agents.collector import collector_node
from core.agents.hypothesis import hypothesis_node
from core.agents.validator import validator_node
from core.agents.communicator import communicator_node


def build_graph(config: ProjectConfig, send_notifications: bool = True):
    graph = StateGraph(DiagnosisState)

    graph.add_node("collector", lambda state: collector_node(state, config))
    graph.add_node("hypothesis", lambda state: hypothesis_node(state, config))
    graph.add_node("validator", lambda state: validator_node(state, config))
    graph.add_node(
        "communicator",
        lambda state: communicator_node(state, config, send=send_notifications),
    )

    graph.set_entry_point("collector")
    graph.add_edge("collector", "hypothesis")
    graph.add_edge("hypothesis", "validator")
    graph.add_edge("validator", "communicator")
    graph.add_edge("communicator", END)

    return graph.compile()


def run_diagnosis(
    config: ProjectConfig,
    incident_id: str,
    trigger_source: str = "manual_test",
    trigger_summary: str = "",
    send_notifications: bool = True,
) -> DiagnosisState:
    compiled_graph = build_graph(config, send_notifications=send_notifications)

    initial_state: DiagnosisState = {
        "incident_id": incident_id,
        "project_name": config.name,
        "manifest_path": "",
        "trigger_source": trigger_source,
        "trigger_summary": trigger_summary,
        "cost_breakdown": [],
    }

    final_state = compiled_graph.invoke(initial_state)
    return final_state


if __name__ == "__main__":
    import json
    from core.config import load_project_config

    config = load_project_config("manifests/rag-demo.yaml")

    result = run_diagnosis(
        config,
        incident_id="test-graph-001",
        trigger_source="manual_test",
        trigger_summary="",
        send_notifications=False,
    )

    print("=== Mensaje final ===")
    print(result["final_message"])
    print()
    print("=== Metadata ===")
    print(f"Escalado a Bedrock: {result.get('escalated_to_bedrock')}")
    print(f"Nivel de confianza: {result.get('confidence_level')}")
    print(f"Costo total (breakdown): {json.dumps(result.get('cost_breakdown', []), indent=2)}")
