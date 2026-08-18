"""
Guardrail de gasto para escalaciones a Bedrock. Limite GLOBAL (no por
proyecto) de escalaciones por hora, para proteger contra un bug o un
proyecto ruidoso que dispare escalaciones en bucle sin que nadie se
entere hasta la factura de AWS.

Usa el mismo patron de escritura atomica que dedup/fingerprint.py:
una condicion en la propia escritura a DynamoDB, no una lectura seguida
de una escritura separada -- eso evitaria condiciones de carrera si
dos incidentes casi simultaneos estan cerca del limite.
"""
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

DEFAULT_MAX_ESCALATIONS_PER_HOUR = 3
TABLE_NAME = "oncall-agent-escalation-budget"
BUCKET_TTL_SECONDS = 2 * 60 * 60  # 2 horas, suficiente margen sobre el bucket de 1h


@dataclass
class BudgetCheckResult:
    allowed: bool
    hour_bucket: str
    current_count: int


def _current_hour_bucket() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")


def check_and_increment_escalation_budget(
    region: str,
    max_per_hour: int = DEFAULT_MAX_ESCALATIONS_PER_HOUR,
    aws_client=None,
) -> BudgetCheckResult:
    hour_bucket = _current_hour_bucket()
    table = (aws_client or boto3.resource("dynamodb", region_name=region)).Table(TABLE_NAME)
    expires_at = int(time.time()) + BUCKET_TTL_SECONDS

    try:
        response = table.update_item(
            Key={"hour_bucket": hour_bucket},
            UpdateExpression="ADD escalation_count :inc SET expires_at = :exp",
            ConditionExpression="attribute_not_exists(escalation_count) OR escalation_count < :limit",
            ExpressionAttributeValues={
                ":inc": 1,
                ":limit": max_per_hour,
                ":exp": expires_at,
            },
            ReturnValues="UPDATED_NEW",
        )
        new_count = int(response["Attributes"]["escalation_count"])
        return BudgetCheckResult(allowed=True, hour_bucket=hour_bucket, current_count=new_count)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return BudgetCheckResult(allowed=False, hour_bucket=hour_bucket, current_count=max_per_hour)
        raise


if __name__ == "__main__":
    import sys

    region = sys.argv[1] if len(sys.argv) > 1 else "us-east-1"
    max_per_hour = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MAX_ESCALATIONS_PER_HOUR

    print(f"=== Probando guardrail con limite de {max_per_hour}/hora ===")
    for i in range(max_per_hour + 2):
        result = check_and_increment_escalation_budget(region, max_per_hour)
        print(f"Intento {i + 1}: allowed={result.allowed}, count={result.current_count}, bucket={result.hour_bucket}")
