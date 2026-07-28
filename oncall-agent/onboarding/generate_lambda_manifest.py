"""
Genera el manifiesto de Lambda a partir del manifiesto base de desarrollo,
ajustando las rutas relativas de sistema de archivos (root_path,
knowledge_base.path) al layout del paquete de Lambda -- donde
monitored-systems/ es hermano directo de manifests/, en vez de estar un
nivel arriba como en el repo de desarrollo local.

Las rutas de S3 (postmortem_store_path) no se tocan, porque una URI
s3://... es la misma sin importar dónde corra el código.
"""
import sys
from pathlib import Path

import yaml


def generate_lambda_manifest(base_manifest_path: Path, output_path: Path) -> None:
    with open(base_manifest_path) as f:
        raw = yaml.safe_load(f)

    project_name = raw["project"]["name"]

    def adjust_path(path_str: str) -> str:
        if path_str.startswith("s3://"):
            return path_str
        if path_str.startswith("../../"):
            return path_str.replace("../../", "../", 1)
        if path_str.startswith("/"):
            # Ruta absoluta local (proyecto fuera del repo del agente) --
            # en el paquete de Lambda, el codigo de este proyecto vive
            # SIEMPRE en monitored-systems/<project.name>/, sin importar
            # como se llame la carpeta local -- consistencia garantizada
            # por el nombre declarado en el manifiesto, no por convencion
            # de directorios.
            if path_str.endswith(".json"):
                return f"../monitored-systems/{project_name}/.oncall/knowledge_base.json"
            return f"../monitored-systems/{project_name}"
        return path_str

    raw["project"]["root_path"] = adjust_path(raw["project"]["root_path"])
    raw["knowledge_base"]["path"] = adjust_path(raw["knowledge_base"]["path"])

    if "postmortem_store_path" in raw.get("memory", {}):
        raw["memory"]["postmortem_store_path"] = adjust_path(raw["memory"]["postmortem_store_path"])

    with open(output_path, "w") as f:
        yaml.safe_dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


if __name__ == "__main__":
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("manifests/rag-demo.yaml")
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("manifests/rag-demo-lambda.yaml")

    generate_lambda_manifest(base, output)
    print(f"Manifiesto de Lambda generado: {output}")
    print(f"(a partir de: {base})")
