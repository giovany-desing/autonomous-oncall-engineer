"""
Handler de Slack Events API. Recibe eventos cuando alguien responde en
un hilo del canal de notificaciones. Si el hilo corresponde a un
incidente conocido (existe en DynamoDB), recupera el contexto real
usado en el diagnostico original y responde la pregunta con Groq,
basandose en esa evidencia -- no inventa nada nuevo.
"""
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3
import requests
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

CONTEXT_TABLE_NAME = "oncall-agent-incident-context"
BOT_USER_ID_CACHE = {}

SYSTEM_PROMPT = """Eres el mismo agente SRE que genero un diagnostico de \
incidente. Un desarrollador esta respondiendo en el hilo de ese \
diagnostico con una pregunta de seguimiento. Responde SOLO basandote \
en la evidencia real que se te provee (hipotesis validada, funciones \
candidatas, logs, postmortems similares) -- si la pregunta pide algo \
que esa evidencia no cubre, dilo honestamente en vez de inventar. Se \
breve y directo, esto es una respuesta de chat, no un reporte."""


def _verify_slack_signature(headers: dict, body: str) -> bool:
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    timestamp = headers.get("x-slack-request-timestamp", "")

    if abs(time.time() - int(timestamp or 0)) > 60 * 5:
        return False

    basestring = f"v0:{timestamp}:{body}"
    computed_signature = "v0=" + hmac.new(
        signing_secret.encode(), basestring.encode(), hashlib.sha256
    ).hexdigest()

    slack_signature = headers.get("x-slack-signature", "")
    return hmac.compare_digest(computed_signature, slack_signature)


def _get_bot_user_id() -> str:
    if "id" in BOT_USER_ID_CACHE:
        return BOT_USER_ID_CACHE["id"]

    response = requests.post(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"},
    )
    bot_id = response.json().get("user_id", "")
    BOT_USER_ID_CACHE["id"] = bot_id
    return bot_id


def _load_incident_context(thread_ts: str, region: str = "us-east-1") -> dict:
    table = boto3.resource("dynamodb", region_name=region).Table(CONTEXT_TABLE_NAME)
    response = table.get_item(Key={"thread_ts": thread_ts})
    return response.get("Item")


def _answer_question(context: dict, question: str, model: str = "llama-3.3-70b-versatile") -> str:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    evidence = f"""Incidente: {context.get('incident_id')} - proyecto {context.get('project_name')}
Nivel de confianza del diagnostico original: {context.get('confidence_level')}

Hipotesis validada:
{context.get('validated_hypothesis', '{}')}

Funciones candidatas de codigo:
{context.get('candidate_functions', '[]')}

Logs recientes (ultimos 20 eventos):
{context.get('log_events', '[]')}

Postmortems similares encontrados:
{context.get('similar_postmortems', '[]')}
"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Evidencia del incidente:\n{evidence}\n\nPregunta del desarrollador: {question}"},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content


def _reply_in_thread(channel: str, thread_ts: str, text: str) -> None:
    requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"},
        json={"channel": channel, "thread_ts": thread_ts, "text": text},
    )


def lambda_handler(event, context):
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    body = event.get("body", "")

    payload = json.loads(body)

    if payload.get("type") == "url_verification":
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/plain"},
            "body": payload.get("challenge", ""),
        }

    if not _verify_slack_signature(headers, body):
        return {"statusCode": 401, "body": "Firma invalida"}

    slack_event = payload.get("event", {})
    print(f"DEBUG payload_type={payload.get('type')} event_type={slack_event.get('type')} "
          f"bot_id={slack_event.get('bot_id')} user={slack_event.get('user')} "
          f"thread_ts={slack_event.get('thread_ts')} text={slack_event.get('text')}")

    if slack_event.get("type") != "message":
        print(f"DEBUG: ignorado porque type={slack_event.get('type')} != 'message'")
        return {"statusCode": 200, "body": "ignorado"}

    bot_user_id = _get_bot_user_id()
    print(f"DEBUG: bot_user_id={bot_user_id}")
    if slack_event.get("bot_id") or slack_event.get("user") == bot_user_id:
        print("DEBUG: ignorado porque es mensaje propio del bot")
        return {"statusCode": 200, "body": "ignorado (mensaje propio)"}

    thread_ts = slack_event.get("thread_ts")
    if not thread_ts:
        print("DEBUG: ignorado porque no tiene thread_ts")
        return {"statusCode": 200, "body": "ignorado (no es respuesta en hilo)"}

    incident_context = _load_incident_context(thread_ts)
    print(f"DEBUG: incident_context encontrado={incident_context is not None}")
    if not incident_context:
        print(f"DEBUG: ignorado - no se encontro contexto para thread_ts={thread_ts}")
        return {"statusCode": 200, "body": "ignorado (hilo no corresponde a un incidente conocido)"}

    question = slack_event.get("text", "")

    try:
        answer = _answer_question(incident_context, question)
    except Exception as e:
        print(f"ERROR al generar respuesta: {e}")
        _reply_in_thread(
            slack_event["channel"],
            thread_ts,
            "No pude generar una respuesta en este momento (limite de la API alcanzado o error temporal). Intenta de nuevo en unos minutos.",
        )
        return {"statusCode": 200, "body": "error notificado al usuario"}

    _reply_in_thread(slack_event["channel"], thread_ts, answer)

    return {"statusCode": 200, "body": "respondido"}
