"""
Pasada 2 del onboarding: comprensión de arquitectura vía LLM.
Toma el resultado del scanner estructural (Pasada 1) + el README del
proyecto monitoreado, prioriza el código riesgoso, y le pide a un LLM
barato (Groq/Llama) un resumen de arquitectura + mapa de puntos frágiles.
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

from structural_scan import scan_directory

load_dotenv()

RISK_ORDER = {"alto": 0, "medio": 1, "bajo": 2}

SYSTEM_PROMPT = """Eres un ingeniero SRE senior explorando un repositorio \
por primera vez. Recibes: (1) el README del proyecto, si existe, y (2) un \
mapa estructural generado por análisis estático (funciones, llamadas a \
servicios externos, y bloques de manejo de errores clasificados por \
riesgo: alto = captura silenciosa total, medio = captura parcial, \
bajo = maneja el error correctamente).

Responde ÚNICAMENTE con un JSON válido (sin texto adicional, sin markdown) \
con esta forma exacta:
{
  "resumen_arquitectura": "string: qué hace el sistema y cómo fluyen los datos, 3-5 oraciones",
  "puntos_fragiles": [
    {
      "funcion": "nombre de la función",
      "archivo": "ruta del archivo",
      "riesgo": "alto|medio|bajo",
      "por_que": "explicación breve de por qué es frágil, 1-2 oraciones",
      "depende_de": ["lista de servicios externos de los que depende, si aplica"]
    }
  ]
}

Si no hay README, dilo explícitamente dentro de resumen_arquitectura en \
vez de inventar contexto que no tienes."""


def _read_readme(project_root: Path) -> str:
    for name in ("README.md", "readme.md", "Readme.md"):
        candidate = project_root / name
        if candidate.exists():
            return candidate.read_text()
    return "(No se encontró README.md en este proyecto)"


def _build_user_prompt(readme: str, scan_results: list) -> str:
    all_error_blocks = []
    all_functions = []
    for result in scan_results:
        all_error_blocks.extend(result.error_blocks)
        all_functions.extend(result.functions)

    all_error_blocks.sort(key=lambda b: RISK_ORDER.get(b.risk, 3))

    functions_by_key = {
        (f.file, f.name): f for f in all_functions
    }

    fragile_summaries = []
    for block in all_error_blocks:
        fn = functions_by_key.get((block.file, block.enclosing_function))
        external_calls = fn.external_calls if fn else []
        fragile_summaries.append({
            "archivo": block.file,
            "funcion": block.enclosing_function,
            "riesgo": block.risk,
            "lineas": f"{block.line_start}-{block.line_end}",
            "tipo_excepcion": block.exception_type,
            "llamadas_externas": external_calls,
        })

    prompt = f"""README del proyecto:
---
{readme}
---

Mapa estructural (bloques de manejo de errores, ordenados de mayor a menor riesgo):
{json.dumps(fragile_summaries, indent=2, ensure_ascii=False)}

Total de funciones catalogadas: {len(all_functions)}
"""
    return prompt


def generate_architecture_summary(
    project_root: Path,
    model: str = "llama-3.3-70b-versatile",
    extra_context: str = "",
) -> dict:
    readme = _read_readme(project_root)
    scan_results = scan_directory(project_root)
    user_prompt = _build_user_prompt(readme, scan_results)
    if extra_context.strip():
        user_prompt += f"\n\nDocumentacion adicional provista por el usuario (infraestructura o logica de negocio):\n---\n{extra_context.strip()}\n---\n"

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    usage = response.usage
    result = json.loads(content)
    result["_metadata"] = {
        "model": model,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }
    return result


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    summary = generate_architecture_summary(target)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
