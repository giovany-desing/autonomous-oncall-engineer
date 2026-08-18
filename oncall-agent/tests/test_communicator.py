"""
Tests para el nodo Comunicador, especificamente _save_cost_log.

Este modulo es nuevo (Fase 2 - FinOps): antes del cambio, el costo de
cada incidente se calculaba y se mandaba a Slack, pero nunca quedaba
persistido en ningun lado consultable. Este test protege la escritura
a DynamoDB, para que un fallo silencioso aqui (como el que ya paso una
vez con el pricing de un modelo desconocido) se detecte en CI, no en
produccion.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agents.communicator import _save_cost_log, COST_LOG_TABLE_NAME


def test_save_cost_log_escribe_item_con_campos_esperados(mocker):
    mock_table = mocker.MagicMock()
    mock_resource = mocker.MagicMock()
    mock_resource.Table.return_value = mock_table
    mocker.patch("core.agents.communicator.boto3.resource", return_value=mock_resource)

    state = {
        "incident_id": "inc-123",
        "project_name": "rag-demo",
        "escalated_to_bedrock": True,
        "confidence_level": "alta",
        "cost_breakdown": [
            {"model": "openai/gpt-oss-120b", "prompt_tokens": 100, "completion_tokens": 50},
            {"model": "anthropic.claude-sonnet-5", "prompt_tokens": 200, "completion_tokens": 80},
        ],
    }

    _save_cost_log(state, cost_usd=0.0042, region="us-east-1")

    mock_resource.Table.assert_called_once_with(COST_LOG_TABLE_NAME)
    mock_table.put_item.assert_called_once()

    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["incident_id"] == "inc-123"
    assert item["project_name"] == "rag-demo"
    assert item["cost_usd"] == "0.0042"
    assert item["escalated_to_bedrock"] is True
    assert item["confidence_level"] == "alta"
    assert item["models_used"] == ["anthropic.claude-sonnet-5", "openai/gpt-oss-120b"]


def test_save_cost_log_sin_modelos_usados_no_falla(mocker):
    mock_table = mocker.MagicMock()
    mock_resource = mocker.MagicMock()
    mock_resource.Table.return_value = mock_table
    mocker.patch("core.agents.communicator.boto3.resource", return_value=mock_resource)

    state = {
        "incident_id": "inc-456",
        "project_name": "rag-demo",
        "cost_breakdown": [],
    }

    _save_cost_log(state, cost_usd=0.0, region="us-east-1")

    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["models_used"] == []
    assert item["cost_usd"] == "0.0"
