"""
Extrae el campo source.repo de un manifiesto, si existe. Usado por el
workflow de CI/CD para decidir que proyectos externos clonar, sin
necesitar Python inline dentro del YAML (fragil de mantener).
"""
import sys
import yaml


def extract_source_repo(manifest_path: str) -> str:
    with open(manifest_path) as f:
        raw = yaml.safe_load(f)
    return raw.get("source", {}).get("repo", "")


if __name__ == "__main__":
    manifest_path = sys.argv[1]
    print(extract_source_repo(manifest_path))
