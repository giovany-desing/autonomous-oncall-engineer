"""
Memoria de postmortems: JSON + similitud de coseno sobre embeddings
(MVP, según el documento — Qdrant queda como upgrade si el volumen crece).
Cada postmortem guarda la causa confirmada, la solución aplicada, y si
funcionó, indexado por un embedding de su descripción para búsqueda
semántica en incidentes futuros.
"""
import json
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

EMBEDDING_MODEL = "llama-3.3-70b-versatile"  # placeholder hasta definir modelo de embeddings


@dataclass
class Postmortem:
    id: str
    incident_id: str
    project_name: str
    causa_confirmada: str
    solucion_aplicada: str
    funciono: bool
    descripcion_busqueda: str
    embedding: list = field(default_factory=list)
    created_at: str = ""


def _cosine_similarity(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _embed_text(text: str) -> list:
    """
    Placeholder de embeddings: Groq no ofrece endpoint de embeddings.
    Usamos un hash determinístico de n-gramas como stand-in barato hasta
    decidir el proveedor real de embeddings (ej. AWS Bedrock Titan Embeddings).
    NO usar en producción — ver nota en el Paso 65.
    """
    import hashlib
    vector = []
    words = text.lower().split()
    for i in range(64):
        h = hashlib.md5(f"{i}:{' '.join(words)}".encode()).hexdigest()
        vector.append(int(h[:8], 16) / 0xFFFFFFFF)
    return vector


def load_postmortems(path: Path) -> list:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [Postmortem(**p) for p in data]


def save_postmortem(path: Path, postmortem: Postmortem) -> None:
    existing = load_postmortems(path)
    existing.append(postmortem)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(p) for p in existing], indent=2, ensure_ascii=False))


def find_similar_postmortems(path: Path, query_text: str, top_k: int = 3, min_similarity: float = 0.3) -> list:
    postmortems = load_postmortems(path)
    if not postmortems:
        return []

    query_embedding = _embed_text(query_text)
    scored = [
        (p, _cosine_similarity(query_embedding, p.embedding))
        for p in postmortems
    ]
    scored = [(p, score) for p, score in scored if score >= min_similarity]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [{"postmortem": asdict(p), "similarity": score} for p, score in scored[:top_k]]


def create_postmortem(
    path: Path,
    incident_id: str,
    project_name: str,
    causa_confirmada: str,
    solucion_aplicada: str,
    funciono: bool,
) -> Postmortem:
    descripcion = f"{causa_confirmada}. {solucion_aplicada}"
    postmortem = Postmortem(
        id=f"pm-{incident_id}",
        incident_id=incident_id,
        project_name=project_name,
        causa_confirmada=causa_confirmada,
        solucion_aplicada=solucion_aplicada,
        funciono=funciono,
        descripcion_busqueda=descripcion,
        embedding=_embed_text(descripcion),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    save_postmortem(path, postmortem)
    return postmortem


if __name__ == "__main__":
    test_path = Path("/tmp/test_postmortems.json")
    test_path.unlink(missing_ok=True)

    print("=== Búsqueda sin postmortems (cold start) ===")
    results = find_similar_postmortems(test_path, "error de S3 al descargar archivo")
    print(f"Resultados: {results}")

    print("\n=== Creando un postmortem de prueba ===")
    pm = create_postmortem(
        test_path,
        incident_id="test-001",
        project_name="rag-demo",
        causa_confirmada="Excepción silenciosa en process_upload al parsear JSON malformado",
        solucion_aplicada="Agregar logging explícito y re-raise en el except de process_upload",
        funciono=True,
    )
    print(f"Postmortem creado: {pm.id}")

    print("\n=== Búsqueda con 1 postmortem existente ===")
    results = find_similar_postmortems(test_path, "fallo al procesar archivo subido a S3")
    for r in results:
        print(f"  Similitud: {r['similarity']:.3f} - {r['postmortem']['causa_confirmada']}")
