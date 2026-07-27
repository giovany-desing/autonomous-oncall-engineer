"""
Carga y valida el manifiesto YAML de un proyecto monitoreado.
Todas las rutas del manifiesto se resuelven relativas a la ubicación del
propio archivo YAML, no al directorio de trabajo actual.
"""
from dataclasses import dataclass
from pathlib import Path

import yaml

REQUIRED_TOP_LEVEL_KEYS = {"project", "knowledge_base", "aws", "llm", "notifications"}


@dataclass
class ProjectConfig:
    name: str
    root_path: Path
    language: str
    knowledge_base_path: Path
    aws_region: str
    resource_tag_key: str
    resource_tag_value: str
    log_groups: list
    hypothesis_provider: str
    hypothesis_model: str
    escalation_provider: str
    escalation_model: str
    escalation_region: str
    notification_channel: str
    notification_webhook_env_var: str
    postmortem_store_path: str  # ruta local o URI s3://bucket/key
    probe_s3_bucket: str
    probe_injected_payload: str
    probe_injected_key_prefix: str
    raw: dict


def _resolve(manifest_dir: Path, relative_path: str) -> Path:
    return (manifest_dir / relative_path).resolve()


def load_project_config(manifest_path: str | Path) -> ProjectConfig:
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifiesto no encontrado: {manifest_path}")

    with open(manifest_path) as f:
        raw = yaml.safe_load(f)

    missing = REQUIRED_TOP_LEVEL_KEYS - raw.keys()
    if missing:
        raise ValueError(f"Manifiesto '{manifest_path.name}' incompleto, faltan claves: {missing}")

    manifest_dir = manifest_path.parent

    return ProjectConfig(
        name=raw["project"]["name"],
        root_path=_resolve(manifest_dir, raw["project"]["root_path"]),
        language=raw["project"]["language"],
        knowledge_base_path=_resolve(manifest_dir, raw["knowledge_base"]["path"]),
        aws_region=raw["aws"]["region"],
        resource_tag_key=raw["aws"]["resource_tag"]["key"],
        resource_tag_value=raw["aws"]["resource_tag"]["value"],
        log_groups=raw["aws"].get("log_groups", []),
        hypothesis_provider=raw["llm"]["hypothesis"]["provider"],
        hypothesis_model=raw["llm"]["hypothesis"]["model"],
        escalation_provider=raw["llm"]["escalation"]["provider"],
        escalation_model=raw["llm"]["escalation"]["model"],
        escalation_region=raw["llm"]["escalation"]["region"],
        notification_channel=raw["notifications"]["channel"],
        notification_webhook_env_var=raw["notifications"]["webhook_env_var"],
        postmortem_store_path=(
            raw["memory"]["postmortem_store_path"]
            if raw["memory"]["postmortem_store_path"].startswith("s3://")
            else str(_resolve(manifest_dir, raw["memory"]["postmortem_store_path"]))
        ),
        probe_s3_bucket=raw.get("probe", {}).get("s3_bucket", ""),
        probe_injected_payload=raw.get("probe", {}).get("injected_payload", ""),
        probe_injected_key_prefix=raw.get("probe", {}).get("injected_key_prefix", ""),
        raw=raw,
    )


if __name__ == "__main__":
    import sys
    import json

    manifest = sys.argv[1] if len(sys.argv) > 1 else "manifests/rag-demo.yaml"
    config = load_project_config(manifest)
    print(f"Proyecto: {config.name}")
    print(f"Root path: {config.root_path}")
    print(f"Root path existe: {config.root_path.exists()}")
    print(f"Knowledge base path: {config.knowledge_base_path}")
    print(f"Knowledge base existe: {config.knowledge_base_path.exists()}")
    print(f"Tag AWS: {config.resource_tag_key}={config.resource_tag_value}")
    print(f"Modelo hipótesis: {config.hypothesis_provider}/{config.hypothesis_model}")
    print(f"Modelo escalamiento: {config.escalation_provider}/{config.escalation_model}")
