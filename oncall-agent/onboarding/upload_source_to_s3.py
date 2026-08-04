"""
Sube el codigo fuente completo de un proyecto a S3, reflejando la
estructura real de carpetas. Se corre como parte del onboarding (local
o CI/CD) para que el chat conversacional (via agent_tools.py) siempre
tenga acceso a la version mas reciente del codigo, sin depender de que
este empaquetado en el zip de Lambda.
"""
import sys
from pathlib import Path

import boto3

SOURCE_BUCKET = "oncall-agent-memory-531728396479"
EXCLUDED_DIR_NAMES = {
    ".venv", "venv", "__pycache__", "node_modules", "build", "dist",
    "site-packages", ".git", ".terraform", ".oncall",
}
INCLUDED_EXTENSIONS = {".py", ".md", ".yaml", ".yml", ".json", ".txt", ".toml"}
MAX_FILE_SIZE_BYTES = 500_000  # no subir archivos gigantes (ej. datos binarios mal detectados)


def upload_source(project_root: Path, project_name: str) -> int:
    client = boto3.client("s3")
    prefix = f"source-code/{project_name}/"

    uploaded = 0
    for file_path in project_root.rglob("*"):
        if not file_path.is_file():
            continue
        if any(part in EXCLUDED_DIR_NAMES for part in file_path.parts):
            continue
        if file_path.suffix not in INCLUDED_EXTENSIONS:
            continue
        if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
            continue

        relative_path = file_path.relative_to(project_root)
        key = f"{prefix}{relative_path.as_posix()}"

        client.upload_file(str(file_path), SOURCE_BUCKET, key)
        uploaded += 1

    return uploaded


if __name__ == "__main__":
    project_root = Path(sys.argv[1])
    project_name = sys.argv[2]

    count = upload_source(project_root, project_name)
    print(f"Subidos {count} archivos de codigo fuente a s3://{SOURCE_BUCKET}/source-code/{project_name}/")
