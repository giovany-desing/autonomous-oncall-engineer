"""
Estado compartido del grafo de LangGraph para el pipeline de diagnóstico.
Cada nodo (Recolector, Hipótesis, Validador, Comunicador) lee de este
estado y le agrega su propia evidencia — nunca borra lo que otro nodo
ya escribió, solo acumula.
"""
from typing import TypedDict, Optional


class Hypothesis(TypedDict):
    causa_probable: str
    explicacion: str
    solucion_propuesta: str
    confianza: float  # 0.0 a 1.0


class DiagnosisState(TypedDict, total=False):
    # --- Entrada inicial (la pone quien invoca el grafo) ---
    incident_id: str
    project_name: str
    manifest_path: str
    trigger_source: str  # "cloudwatch" | "synthetic_probe"
    trigger_summary: str  # ej. el mensaje de log que disparó el incidente

    # --- Evidencia recolectada por el nodo Recolector ---
    log_events: list
    has_explicit_error: bool
    request_ids: list
    candidate_functions: list  # funciones candidatas del code_adapter
    tagged_resources: list
    lambda_config: Optional[dict]
    external_connection_stats: list

    # --- Producido por el nodo Hipótesis ---
    hypotheses: list  # list[Hypothesis], rankeadas
    escalated_to_bedrock: bool
    escalation_reason: str
    escalation_blocked_by_budget: bool  # True si el guardrail de gasto impidio una escalacion que si aplicaba

    # --- Producido por el nodo Validador ---
    similar_postmortems: list
    validated_hypothesis: Optional[Hypothesis]
    confidence_level: str  # "alta" | "media" | "baja" | "insuficiente"

    # --- Producido por el nodo Comunicador ---
    final_message: str
    notification_sent: bool

    # --- Metadata de costo, acumulada por cada nodo ---
    cost_breakdown: list  # [{"node": str, "provider": str, "tokens": int, "usd": float}]
