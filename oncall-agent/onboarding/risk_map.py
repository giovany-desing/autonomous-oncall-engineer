"""
Combina la Pasada 1 (structural_scan) y la Pasada 2 (architecture_summary)
en un único artefacto: la "base de conocimiento del sistema".

Este artefacto se persiste en disco (JSON) y es lo que el Recolector
consulta en cada diagnóstico posterior — el onboarding completo no se
vuelve a correr por incidente, solo cuando el proyecto cambia de forma
significativa (disparado por CI/CD).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from structural_scan import scan_directory
from architecture_summary import generate_architecture_summary
from dataclasses import asdict


def build_knowledge_base(
    project_root: Path,
    model: str = "openai/gpt-oss-120b",
    extra_context: str = "",
) -> dict:
    scan_results = scan_directory(project_root)
    arch_summary = generate_architecture_summary(project_root, model=model, extra_context=extra_context)

    all_functions = []
    all_error_blocks = []
    for result in scan_results:
        all_functions.extend(asdict(f) for f in result.functions)
        all_error_blocks.extend(asdict(e) for e in result.error_blocks)

    knowledge_base = {
        "project_root": str(project_root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "resumen_arquitectura": arch_summary["resumen_arquitectura"],
        "puntos_fragiles": arch_summary["puntos_fragiles"],
        "funciones": all_functions,
        "bloques_manejo_errores": all_error_blocks,
        "_metadata": arch_summary["_metadata"],
    }
    return knowledge_base


def save_knowledge_base(knowledge_base: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(knowledge_base, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("knowledge_base.json")

    kb = build_knowledge_base(target)
    save_knowledge_base(kb, output)

    print(f"Base de conocimiento guardada en: {output}")
    print(f"Funciones catalogadas: {len(kb['funciones'])}")
    print(f"Bloques de manejo de errores: {len(kb['bloques_manejo_errores'])}")
    print(f"Puntos frágiles identificados: {len(kb['puntos_fragiles'])}")
    print(f"Costo de esta corrida (tokens): {kb['_metadata']['total_tokens']}")
