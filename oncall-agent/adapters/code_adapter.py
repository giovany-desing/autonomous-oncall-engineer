"""
Adaptador de código. Localiza la función/archivo exacto relevante a un
incidente consultando la base de conocimiento ya generada en el onboarding
(risk_map.py) — búsqueda exacta, no semántica: el nombre de función es un
identificador preciso, no algo que necesite similitud de embeddings.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FunctionLookupResult:
    found: bool
    file: str = ""
    name: str = ""
    line_start: int = 0
    line_end: int = 0
    external_calls: list = field(default_factory=list)
    risk_blocks: list = field(default_factory=list)


def load_knowledge_base(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Base de conocimiento no encontrada en {path}. "
            f"Corre el onboarding (risk_map.py) primero."
        )
    return json.loads(path.read_text())


def find_function(knowledge_base: dict, function_name: str) -> FunctionLookupResult:
    for fn in knowledge_base.get("funciones", []):
        if fn["name"] == function_name:
            risk_blocks = [
                b for b in knowledge_base.get("bloques_manejo_errores", [])
                if b["enclosing_function"] == function_name
            ]
            return FunctionLookupResult(
                found=True,
                file=fn["file"],
                name=fn["name"],
                line_start=fn["line_start"],
                line_end=fn["line_end"],
                external_calls=fn["external_calls"],
                risk_blocks=risk_blocks,
            )
    return FunctionLookupResult(found=False)


# Palabras genericas en español/ingles que no aportan como termino de
# busqueda por si solas -- filtrarlas evita que "configuracion de la
# base de datos" solo matchee por la palabra "de" o "la".
STOPWORDS = {
    "de", "la", "el", "los", "las", "en", "un", "una", "y", "o", "que",
    "the", "of", "a", "an", "in", "on", "for", "and", "or",
}


def search_functions_by_keyword(knowledge_base: dict, keyword: str, limit: int = 5) -> list:
    """
    Busqueda de texto simple (no semantica) sobre nombre de funcion,
    nombre de archivo, y codigo fuente. Separa la consulta en palabras
    individuales (ignorando stopwords) y rankea por cuantas de esas
    palabras aparecen -- asi una consulta en lenguaje natural como
    "configuracion de la base de datos" encuentra archivos que
    contengan "configuracion", "base", o "datos", no solo si contienen
    la frase exacta completa.
    """
    words = [w for w in keyword.lower().split() if w not in STOPWORDS and len(w) > 2]
    if not words:
        words = [keyword.lower()]

    scored = []
    for fn in knowledge_base.get("funciones", []):
        haystack = f"{fn['name']} {fn['file']} {fn.get('source_code', '')}".lower()
        score = sum(1 for w in words if w in haystack)
        if score > 0:
            scored.append((score, fn))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [fn for _, fn in scored[:limit]]


def find_functions_by_risk(knowledge_base: dict, risk: str = "alto") -> list:
    """
    Devuelve las funciones que tienen al menos un bloque de manejo de
    errores del nivel de riesgo dado. Útil cuando el log no da un nombre
    de función explícito, pero sí sabemos qué recurso falló.
    """
    fn_names_with_risk = {
        b["enclosing_function"]
        for b in knowledge_base.get("bloques_manejo_errores", [])
        if b["risk"] == risk
    }
    return [find_function(knowledge_base, name) for name in fn_names_with_risk]


if __name__ == "__main__":
    import sys

    kb_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "../monitored-systems/rag-demo/.oncall/knowledge_base.json"
    )
    knowledge_base = load_knowledge_base(kb_path)

    print("=== Funciones con riesgo alto (candidatas cuando no hay log explícito) ===")
    for result in find_functions_by_risk(knowledge_base, risk="alto"):
        print(f"  {result.name} ({result.file}:{result.line_start}-{result.line_end})")
        print(f"    Llamadas externas: {result.external_calls}")
        print(f"    Bloques de riesgo: {len(result.risk_blocks)}")

    print()
    target = sys.argv[2] if len(sys.argv) > 2 else "process_upload"
    print(f"=== Búsqueda directa: '{target}' ===")
    result = find_function(knowledge_base, target)
    print(json.dumps(result.__dict__, indent=2, ensure_ascii=False))
