"""
Handler de Slack Events API. Recibe eventos cuando alguien responde en
un hilo del canal de notificaciones. Usa tool calling con 4
herramientas reales (leer archivo completo, listar estructura del
proyecto, buscar en base de conocimiento, consultar infraestructura de
AWS) para comportarse como un agente que explora el proyecto antes de
responder -- no solo repite el contexto congelado del diagnostico
original.
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

from core.agent_tools import (
    leer_archivo,
    listar_archivos,
    buscar_en_codigo,
    consultar_infraestructura,
)

load_dotenv()

CONTEXT_TABLE_NAME = "oncall-agent-incident-context"
BOT_USER_ID_CACHE = {}
MAX_TOOL_ROUNDS = 4

SYSTEM_PROMPT = """Eres un ingeniero SRE senior que ya diagnostico un \
incidente de produccion y ahora conversa con un desarrollador en el \
hilo de esa notificacion. Tu objetivo es ayudar de forma completa y \
concreta, como lo haria un compañero senior con acceso total al \
proyecto -- no como un sistema limitado a un resumen.

Tienes herramientas para EXPLORAR ACTIVAMENTE el proyecto real:
- listar_archivos: ver la estructura de carpetas/archivos
- leer_archivo: leer el contenido completo de un archivo especifico
- buscar_en_codigo: buscar funciones por palabra clave en la base de conocimiento
- consultar_infraestructura: ver configuracion real de AWS (Lambda, memoria, timeout, recursos etiquetados)

REGLAS DE COMPORTAMIENTO, OBLIGATORIAS:

1. NUNCA propongas codigo, un diff, o una correccion sin haber llamado leer_archivo sobre el archivo exacto que vas a modificar EN ESTA MISMA CONVERSACION. Si no lo has leido, tu primera accion debe ser leerlo, no responder. Citar codigo de memoria o inventar el contenido de un archivo (incluyendo placeholders como "tu_valor_aqui") esta PROHIBIDO -- si no leiste el archivo, no sabes que hay en el.

2. Si la pregunta menciona "codigo exacto", "diff", "como probarlo", "plan completo", o pide multiples cosas a la vez: trata cada parte como una sub-tarea que requiere su propia exploracion. Ejemplo: para "codigo exacto" -> leer_archivo del archivo relevante. Para "como probarlo" -> leer_archivo de requirements.txt o buscar archivos de test con listar_archivos. No respondas la pregunta completa hasta haber reunido evidencia real para cada parte.

3. Cuando expliques una causa raiz, cita el codigo REAL que leiste (copia el fragmento relevante), no una paráfrasis. Nombra archivo y funcion exactos.

4. Cuando propongas una solucion, el codigo debe ser una modificacion directa de lo que leiste con leer_archivo -- mismo estilo, mismos nombres de variables reales del archivo, no una version generica o de ejemplo.

5. Si el desarrollador pregunta como funciona el proyecto en general (util para alguien nuevo en el equipo), explora con listar_archivos y leer_archivo los puntos de entrada relevantes (handlers, rutas, servicios principales) antes de explicar la arquitectura.

6. Solo di "no tengo esa informacion" DESPUES de haber llamado a las herramientas relevantes y no haber encontrado nada -- nunca antes de intentarlo.

7. Se directo y practico, pero no sacrifiques profundidad tecnica ni el uso de herramientas por brevedad.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "listar_archivos",
            "description": "Lista archivos y carpetas de un directorio del proyecto real.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directorio_relativo": {
                        "type": "string",
                        "description": "Ruta relativa del directorio a explorar. Vacio o '.' para la raiz del proyecto.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_archivo",
            "description": "Lee el contenido completo de un archivo especifico del proyecto real.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta_relativa": {
                        "type": "string",
                        "description": "Ruta relativa del archivo, ej. 'app/core/config.py'",
                    }
                },
                "required": ["ruta_relativa"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_en_codigo",
            "description": "Busca funciones en la base de conocimiento por palabra clave (mas rapido que leer archivos completos cuando no se sabe donde buscar).",
            "parameters": {
                "type": "object",
                "properties": {
                    "palabra_clave": {"type": "string", "description": "Termino a buscar"}
                },
                "required": ["palabra_clave"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_infraestructura",
            "description": "Consulta configuracion real de AWS del proyecto: recursos etiquetados, memoria/timeout de Lambda, etc.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOL_FUNCTIONS = {
    "listar_archivos": listar_archivos,
    "leer_archivo": leer_archivo,
    "buscar_en_codigo": buscar_en_codigo,
    "consultar_infraestructura": consultar_infraestructura,
}


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


def _call_tool(project_name: str, tool_name: str, args: dict) -> str:
    func = TOOL_FUNCTIONS.get(tool_name)
    if not func:
        return f"Error: herramienta '{tool_name}' no existe."

    try:
        return func(project_name, **args)
    except Exception as e:
        return f"Error ejecutando {tool_name}: {e}"


def _answer_question(context: dict, question: str, model: str = "llama-3.3-70b-versatile") -> str:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    project_name = context.get("project_name", "")

    evidence = f"""Incidente: {context.get('incident_id')} - proyecto {project_name}
Nivel de confianza del diagnostico original: {context.get('confidence_level')}

Hipotesis validada:
{context.get('validated_hypothesis', '{}')}

Funciones candidatas de codigo (del diagnostico original, NO son todas las del proyecto):
{context.get('candidate_functions', '[]')}

Logs recientes (ultimos 20 eventos):
{context.get('log_events', '[]')}

Postmortems similares encontrados:
{context.get('similar_postmortems', '[]')}
"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Evidencia del incidente:\n{evidence}\n\nPregunta del desarrollador: {question}"},
    ]

    for round_num in range(MAX_TOOL_ROUNDS):
        # En la primera ronda forzamos el uso de alguna herramienta --
        # la observacion real es que con tool_choice="auto" el modelo
        # a veces responde directo (inventando codigo) en preguntas
        # complejas de varias partes, en vez de explorar primero.
        tool_choice = "required" if round_num == 0 else "auto"
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice=tool_choice,
            temperature=0.2,
        )
        message = response.choices[0].message

        if not message.tool_calls:
            return message.content

        messages.append(message)
        for tool_call in message.tool_calls:
            args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
            print(f"DEBUG ronda={round_num} tool={tool_call.function.name} args={args}")
            result = _call_tool(project_name, tool_call.function.name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result[:4000],
            })

    final_response = client.chat.completions.create(model=model, messages=messages, temperature=0.2)
    return final_response.choices[0].message.content


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

    if headers.get("x-slack-retry-num"):
        return {"statusCode": 200, "body": "ignorado (reintento)"}

    slack_event = payload.get("event", {})

    if slack_event.get("type") != "message":
        return {"statusCode": 200, "body": "ignorado"}

    if slack_event.get("bot_id") or slack_event.get("user") == _get_bot_user_id():
        return {"statusCode": 200, "body": "ignorado (mensaje propio)"}

    thread_ts = slack_event.get("thread_ts")
    if not thread_ts:
        return {"statusCode": 200, "body": "ignorado (no es respuesta en hilo)"}

    incident_context = _load_incident_context(thread_ts)
    if not incident_context:
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
