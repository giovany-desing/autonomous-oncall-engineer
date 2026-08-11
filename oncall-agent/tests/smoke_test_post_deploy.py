"""
Smoke test post-deploy: invoca cada Lambda real con un evento minimo y
confirma que responde sin error de import/runtime -- esto habria
detectado el bug de dotenv corrupto (Paso 328) automaticamente, en vez
de descubrirlo horas despues al probar en Slack.

No prueba logica de negocio completa (eso lo cubren los tests
unitarios), solo confirma "la Lambda arranca y responde", que es el
tipo de fallo mas caro de descubrir tarde.
"""
import base64
import gzip
import json
import sys

import boto3

FUNCTIONS_TO_CHECK = [
    "oncall-agent-diagnosis",
    "oncall-agent-synthetic-probe",
    "oncall-agent-slack-events",
]


def _build_cloudwatch_test_event() -> dict:
    log_payload = {
        "messageType": "DATA_MESSAGE",
        "owner": "531728396479",
        "logGroup": "/aws/lambda/rag-demo-handler",
        "logStream": "smoke-test-stream",
        "subscriptionFilters": ["test-filter"],
        "logEvents": [
            {"id": "smoke-test", "timestamp": 0, "message": "smoke test, no deberia procesarse como incidente real"}
        ],
    }
    compressed = gzip.compress(json.dumps(log_payload).encode("utf-8"))
    encoded = base64.b64encode(compressed).decode("utf-8")
    return {"awslogs": {"data": encoded}}


def _build_slack_events_test_event() -> dict:
    return {
        "headers": {},
        "body": json.dumps({"type": "url_verification", "challenge": "smoke-test-challenge"}),
    }


def check_function_responds(client, function_name: str, payload: dict) -> tuple:
    response = client.invoke(
        FunctionName=function_name,
        Payload=json.dumps(payload).encode("utf-8"),
    )
    body = json.loads(response["Payload"].read())
    function_error = response.get("FunctionError")

    if function_error:
        return False, f"FunctionError={function_error}, body={body}"

    return True, "OK"


def main():
    client = boto3.client("lambda", region_name="us-east-1")
    all_passed = True

    for function_name in FUNCTIONS_TO_CHECK:
        if function_name == "oncall-agent-slack-events":
            payload = _build_slack_events_test_event()
        else:
            payload = _build_cloudwatch_test_event()

        passed, detail = check_function_responds(client, function_name, payload)
        status = "OK" if passed else "FALLO"
        print(f"[{status}] {function_name}: {detail}")

        if not passed:
            all_passed = False

    if not all_passed:
        print("\nSMOKE TEST FALLIDO -- al menos una Lambda no responde correctamente")
        sys.exit(1)

    print("\nSMOKE TEST OK -- todas las Lambdas responden correctamente")


if __name__ == "__main__":
    main()
