"""
Memoria de postmortems: JSON + similitud de coseno sobre embeddings
(MVP, según el documento — Qdrant queda como upgrade si el volumen crece).
Persistido en S3 (no en disco local) para sobrevivir entre invocaciones
de Lambda, donde el sistema de archivos es efímero.
"""
import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


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


def _parse_s3_uri(s3_uri: str) -> tuple:
    assert s3_uri.startswith("s3://"), f"Se esperaba una URI s3://, se recibió: {s3_uri}"
    without_prefix = s3_uri[len("s3://"):]
    bucket, _, key = without_prefix.partition("/")
    return bucket, key


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
    NO usar en producción — deuda técnica ya anotada previamente.
    """
    import hashlib
    vector = []
    words = text.lower().split()
    for i in range(64):
        h = hashlib.md5(f"{i}:{' '.join(words)}".encode()).hexdigest()
        vector.append(int(h[:8], 16) / 0xFFFFFFFF)
    return vector


def load_postmortems(s3_uri: str, s3_client=None) -> list:
    bucket, key = _parse_s3_uri(s3_uri)
    client = s3_client or boto3.client("s3")

    try:
        response = client.get_object(Bucket=bucket, Key=key)
        data = json.loads(response["Body"].read())
        return [Postmortem(**p) for p in data]
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return []
        raise


def save_postmortem(s3_uri: str, postmortem: Postmortem, s3_client=None) -> None:
    bucket, key = _parse_s3_uri(s3_uri)
    client = s3_client or boto3.client("s3")

    existing = load_postmortems(s3_uri, s3_client=client)
    existing.append(postmortem)

    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps([asdict(p) for p in existing], indent=2, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )


def find_similar_postmortems(
    s3_uri: str, query_text: str, top_k: int = 3, min_similarity: float = 0.3, s3_client=None
) -> list:
    postmortems = load_postmortems(s3_uri, s3_client=s3_client)
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
    s3_uri: str,
    incident_id: str,
    project_name: str,
    causa_confirmada: str,
    solucion_aplicada: str,
    funciono: bool,
    s3_client=None,
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
    save_postmortem(s3_uri, postmortem, s3_client=s3_client)
    return postmortem


if __name__ == "__main__":
    test_uri = "s3://oncall-agent-memory-531728396479/test/postmortems.json"

    print("=== Búsqueda sin postmortems (cold start) ===")
    results = find_similar_postmortems(test_uri, "error de S3 al descargar archivo")
    print(f"Resultados: {results}")

    print("\n=== Creando un postmortem de prueba ===")
    pm = create_postmortem(
        test_uri,
        incident_id="test-s3-001",
        project_name="rag-demo",
        causa_confirmada="Excepción silenciosa en process_upload al parsear JSON malformado",
        solucion_aplicada="Agregar logging explícito y re-raise en el except de process_upload",
        funciono=True,
    )
    print(f"Postmortem creado: {pm.id}")

    print("\n=== Búsqueda con 1 postmortem existente ===")
    results = find_similar_postmortems(test_uri, "fallo al procesar archivo subido a S3")
    for r in results:
        print(f"  Similitud: {r['similarity']:.3f} - {r['postmortem']['causa_confirmada']}")
