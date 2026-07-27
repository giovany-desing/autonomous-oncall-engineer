"""
Registro de proyectos monitoreados. Escanea manifests/*.yaml (excluyendo
los *-lambda.yaml, que son artefactos derivados) y construye un mapeo de
log_group -> manifiesto, para que una sola Lambda pueda servir a varios
proyectos sin tener ninguno hardcodeado.
"""
from pathlib import Path

import yaml

MANIFESTS_DIR = Path(__file__).resolve().parent.parent / "manifests"


def _is_base_manifest(path: Path) -> bool:
    return path.suffix in (".yaml", ".yml") and not path.stem.endswith("-lambda")


def list_project_manifests(manifests_dir: Path = MANIFESTS_DIR) -> list:
    return sorted(p for p in manifests_dir.glob("*.y*ml") if _is_base_manifest(p))


def build_log_group_registry(manifests_dir: Path = MANIFESTS_DIR) -> dict:
    """
    Devuelve {log_group: manifest_filename} -- usa el nombre del archivo
    (no la ruta absoluta) porque en Lambda el manifiesto real a cargar es
    la variante *-lambda.yaml generada, no el manifiesto base.
    """
    registry = {}
    for manifest_path in list_project_manifests(manifests_dir):
        with open(manifest_path) as f:
            raw = yaml.safe_load(f)
        for log_group in raw.get("aws", {}).get("log_groups", []):
            registry[log_group] = manifest_path.stem  # ej. "rag-demo"
    return registry


def resolve_manifest_for_log_group(log_group: str, use_lambda_variant: bool = True) -> str:
    registry = build_log_group_registry()
    project_stem = registry.get(log_group)
    if project_stem is None:
        raise KeyError(
            f"No hay ningun proyecto registrado para el log group '{log_group}'. "
            f"Proyectos conocidos: {list(registry.values())}"
        )
    suffix = "-lambda.yaml" if use_lambda_variant else ".yaml"
    return f"manifests/{project_stem}{suffix}"


if __name__ == "__main__":
    registry = build_log_group_registry()
    print("=== Registro de proyectos ===")
    for log_group, project in registry.items():
        print(f"  {log_group} -> {project}")

    print()
    test_log_group = "/aws/lambda/rag-demo-handler"
    resolved = resolve_manifest_for_log_group(test_log_group)
    print(f"Resolviendo '{test_log_group}': {resolved}")
