"""
Herramientas reales para el agente conversacional -- le dan acceso de
lectura al proyecto completo (no solo fragmentos congelados en la base
de conocimiento), y a infraestructura real de AWS. Este es el conjunto
de herramientas que convierte el chat de "responde con lo que ya sabia"
a "explora activamente el proyecto antes de responder", igual que
Claude Code.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3
from botocore.exceptions import ClientError

from adapters.aws_resource_adapter import discover_resources_by_tag, get_lambda_config
from adapters.code_adapter import load_knowledge_base, search_functions_by_keyword

MAX_FILE_CHARS = 8000
SOURCE_BUCKET = "oncall-agent-memory-531728396479"


def _s3_source_prefix(project_name: str) -> str:
    return f"source-code/{project_name}/"


def _normalizar_ruta(project_name: str, ruta_relativa: str) -> str:
    """
    El LLM a veces construye rutas basadas en referencias que vio en
    codigo (ej. rutas usadas durante CI/CD como
    "../external-projects/<proyecto>/archivo.py") en vez de la ruta
    real relativa a la raiz del proyecto en S3. Esto normaliza esos
    prefijos comunes antes de consultar S3.
    """
    ruta_relativa = ruta_relativa.strip()
    prefijos_a_quitar = [
        f"../external-projects/{project_name}/",
        f"external-projects/{project_name}/",
        f"../monitored-systems/{project_name}/",
        f"monitored-systems/{project_name}/",
        f"{project_name}/",
    ]
    for prefijo in prefijos_a_quitar:
        if ruta_relativa.startswith(prefijo):
            ruta_relativa = ruta_relativa[len(prefijo):]
            break
    return ruta_relativa.lstrip("/")


def leer_archivo(project_name: str, ruta_relativa: str) -> str:
    """
    Lee el contenido completo de un archivo del proyecto desde S3 (hasta
    MAX_FILE_CHARS). El codigo fuente en S3 se actualiza automaticamente
    en cada push al repo del proyecto -- siempre refleja la version mas
    reciente, sin depender de que este empaquetado en el zip de Lambda.
    """
    ruta_relativa = _normalizar_ruta(project_name, ruta_relativa)
    key = f"{_s3_source_prefix(project_name)}{ruta_relativa}"

    client = boto3.client("s3")
    try:
        response = client.get_object(Bucket=SOURCE_BUCKET, Key=key)
        content = response["Body"].read().decode("utf-8", errors="replace")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return f"Error: el archivo '{ruta_relativa}' no existe en el proyecto (o el onboarding no ha subido el codigo fuente todavia)."
        return f"Error leyendo el archivo: {e}"

    if len(content) > MAX_FILE_CHARS:
        content = content[:MAX_FILE_CHARS] + "\n... (archivo truncado, es mas largo)"

    return f"--- {ruta_relativa} ---\n{content}"


def listar_archivos(project_name: str, directorio_relativo: str = "") -> str:
    """
    Lista los archivos y carpetas dentro de un directorio del proyecto,
    leyendo la estructura real desde S3. Usar para explorar antes de
    decidir que archivo leer, igual que un desarrollador nuevo
    explorando el repo por primera vez.
    """
    directorio_relativo = _normalizar_ruta(project_name, directorio_relativo).strip("/")
    prefix = _s3_source_prefix(project_name)
    if directorio_relativo:
        prefix += directorio_relativo + "/"

    client = boto3.client("s3")
    response = client.list_objects_v2(Bucket=SOURCE_BUCKET, Prefix=prefix, Delimiter="/")

    entries = []
    for common_prefix in response.get("CommonPrefixes", []):
        name = common_prefix["Prefix"][len(prefix):].rstrip("/")
        entries.append(f"{name}/")
    for obj in response.get("Contents", []):
        name = obj["Key"][len(prefix):]
        if name:
            entries.append(name)

    if not entries:
        return f"No se encontraron archivos en '{directorio_relativo or '.'}' (o el proyecto aun no tiene codigo fuente indexado)."

    label = directorio_relativo or "raiz del proyecto"
    return f"Contenido de {label}:\n" + "\n".join(sorted(entries))


def buscar_en_codigo(project_name: str, palabra_clave: str) -> str:
    """
    Busca funciones en la base de conocimiento por palabra clave.
    Herramienta ya existente, se mantiene para busquedas rapidas antes
    de leer archivos completos.
    """
    kb_path = _get_project_root(project_name) / ".oncall" / "knowledge_base.json"
    try:
        knowledge_base = load_knowledge_base(kb_path)
        matches = search_functions_by_keyword(knowledge_base, palabra_clave, limit=5)
        if not matches:
            return f"No se encontraron funciones relacionadas con '{palabra_clave}'."
        import json
        return json.dumps(matches, ensure_ascii=False)
    except Exception as e:
        return f"Error buscando en la base de conocimiento: {e}"


def consultar_logs_recientes(project_name: str, minutos_atras: int = 10, region: str = "us-east-1") -> str:
    """
    Consulta los logs REALES y ACTUALES de CloudWatch para el proyecto,
    en una ventana de tiempo reciente -- distinto de los logs congelados
    del momento del diagnostico original. Usar cuando el desarrollador
    pregunte si un problema sigue ocurriendo, o quiera ver logs de un
    momento mas reciente que el incidente original.
    """
    from adapters.cloudwatch_adapter import fetch_recent_logs
    from core.registry import build_log_group_registry

    registry = build_log_group_registry()
    log_groups = [lg for lg, proj in registry.items() if proj == project_name]

    if not log_groups:
        return f"No se encontraron log groups registrados para el proyecto '{project_name}'."

    all_results = []
    for log_group in log_groups:
        try:
            result = fetch_recent_logs(log_group, region, minutes_back=minutos_atras)
            messages = [e.message.strip() for e in result.events[-15:]]
            all_results.append(
                f"Log group {log_group} (ultimos {minutos_atras} min, "
                f"{len(result.events)} eventos, error explicito={result.has_explicit_error}):\n"
                + "\n".join(messages)
            )
        except Exception as e:
            all_results.append(f"Error consultando {log_group}: {e}")

    return "\n\n".join(all_results)


def consultar_infraestructura(project_name: str, tag_key: str = "oncall-project", region: str = "us-east-1") -> str:
    """
    Consulta la infraestructura real de AWS del proyecto (recursos
    etiquetados, configuracion de Lambda: memoria, timeout, runtime).
    Usar cuando la pregunta es sobre configuracion de despliegue, no
    sobre codigo.
    """
    try:
        resources = discover_resources_by_tag(tag_key, project_name, region)
        if not resources:
            return f"No se encontraron recursos de AWS etiquetados con {tag_key}={project_name}."

        lines = [f"Recursos de AWS para '{project_name}':"]
        for r in resources:
            lines.append(f"  [{r.resource_type}] {r.arn}")

        lambda_resources = [r for r in resources if r.resource_type == "lambda"]
        for lr in lambda_resources:
            function_name = lr.arn.split(":")[-1]
            try:
                config = get_lambda_config(function_name, region)
                lines.append(
                    f"\nConfig de {function_name}: runtime={config.runtime}, "
                    f"memoria={config.memory_size}MB, timeout={config.timeout}s, "
                    f"arquitectura={config.architectures}"
                )
            except Exception:
                pass

        return "\n".join(lines)
    except Exception as e:
        return f"Error consultando infraestructura: {e}"
