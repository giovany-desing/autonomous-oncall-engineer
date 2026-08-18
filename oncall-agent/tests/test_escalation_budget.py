"""
Tests para el guardrail de gasto (Fase 3 - FinOps). Cubre los dos
caminos reales: una escalacion dentro del limite se permite e
incrementa el contador; una escalacion que excede el limite se
bloquea via la misma ConditionalCheckFailedException que ya usa
dedup/fingerprint.py para su propia atomicidad.
"""
import sys
from pathlib import Path

from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from budget.escalation_budget import check_and_increment_escalation_budget


def _conditional_check_failed():
    return ClientError(
        error_response={"Error": {"Code": "ConditionalCheckFailedException", "Message": "test"}},
        operation_name="UpdateItem",
    )


def test_escalacion_dentro_del_limite_se_permite(mocker):
    mock_table = mocker.MagicMock()
    mock_table.update_item.return_value = {"Attributes": {"escalation_count": 2}}
    mock_resource = mocker.MagicMock()
    mock_resource.Table.return_value = mock_table
    mocker.patch("budget.escalation_budget.boto3.resource", return_value=mock_resource)

    result = check_and_increment_escalation_budget(region="us-east-1", max_per_hour=3)

    assert result.allowed is True
    assert result.current_count == 2
    mock_table.update_item.assert_called_once()
    call_kwargs = mock_table.update_item.call_args.kwargs
    assert call_kwargs["ExpressionAttributeValues"][":limit"] == 3


def test_escalacion_que_excede_el_limite_se_bloquea(mocker):
    mock_table = mocker.MagicMock()
    mock_table.update_item.side_effect = _conditional_check_failed()
    mock_resource = mocker.MagicMock()
    mock_resource.Table.return_value = mock_table
    mocker.patch("budget.escalation_budget.boto3.resource", return_value=mock_resource)

    result = check_and_increment_escalation_budget(region="us-east-1", max_per_hour=3)

    assert result.allowed is False
    assert result.current_count == 3


def test_error_distinto_a_condicion_se_repropaga(mocker):
    mock_table = mocker.MagicMock()
    mock_table.update_item.side_effect = ClientError(
        error_response={"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "test"}},
        operation_name="UpdateItem",
    )
    mock_resource = mocker.MagicMock()
    mock_resource.Table.return_value = mock_table
    mocker.patch("budget.escalation_budget.boto3.resource", return_value=mock_resource)

    try:
        check_and_increment_escalation_budget(region="us-east-1", max_per_hour=3)
        assert False, "Se esperaba que ClientError se repropagara"
    except ClientError as e:
        assert e.response["Error"]["Code"] == "ProvisionedThroughputExceededException"
