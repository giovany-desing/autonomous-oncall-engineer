"""
Migracion one-off: re-embede los postmortems existentes que fueron creados
con el placeholder de hash MD5 (deuda tecnica ya corregida en
memory/postmortem_store.py). Sin esto, los postmortems viejos quedarian
con vectores no comparables contra los nuevos embeddings semanticos reales.

Uso:
    python3 scripts/migrate_postmortem_embeddings.py s3://bucket/proyecto/postmortems.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3

from memory.postmortem_store import _embed_text, _parse_s3_uri, Postmortem
from dataclasses import asdict


def migrate(s3_uri: str) -> None:
    bucket, key = _parse_s3_uri(s3_uri)
    client = boto3.client("s3")

    response = client.get_object(Bucket=bucket, Key=key)
    raw_postmortems = json.loads(response["Body"].read())

    print(f"Encontrados {len(raw_postmortems)} postmortem(s) en {s3_uri}")

    migrated = []
    for raw in raw_postmortems:
        pm = Postmortem(**raw)
        old_embedding_len = len(pm.embedding)
        pm.embedding = _embed_text(pm.descripcion_busqueda, s3_client=None)
        print(
            f"  {pm.id}: re-embedido "
            f"(dimension {old_embedding_len} -> {len(pm.embedding)})"
        )
        migrated.append(asdict(pm))

    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(migrated, indent=2, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
    print(f"✅ {len(migrated)} postmortem(s) migrado(s) y guardado(s) en {s3_uri}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python3 migrate_postmortem_embeddings.py s3://bucket/proyecto/postmortems.json")
        sys.exit(1)
    migrate(sys.argv[1])
