"""
Wizard de onboarding: colapsa el proceso completo de conectar un
proyecto nuevo en un solo comando.

Uso:
  python onboarding/onboard_project.py \
    --repo giovany-desing/mi-proyecto \
    --log-group /aws/lambda/mi-proyecto-handler \
    [--pdf docs/arquitectura.pdf --pdf docs/negocio.pdf] \
    [--local-path /ruta/local/si/ya/esta/clonado]

Hace, en cadena: clonar (o usar carpeta local) -> extraer PDFs si los
hay -> onboarding completo (Tree-sitter + Groq) -> generar manifiesto ->
subir base de conocimiento a S3 -> commit + push del manifiesto.

NO hace: aplicar el tag oncall-project en AWS, ni el terraform apply del
subscription filter -- esas dos cosas requieren confirmacion explicita
del usuario sobre que recursos reales pertenecen al proyecto, y se
imprimen como pasos siguientes al final, no se ejecutan solas.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pypdf import PdfReader

from onboarding.risk_map import build_knowledge_base, save_knowledge_base
from onboarding.generate_lambda_manifest import generate_lambda_manifest

AGENT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_BUCKET = "oncall-agent-memory-531728396479"


def _extract_pdf_text(pdf_paths: list) -> str:
    combined = []
    for pdf_path in pdf_paths:
        reader = PdfReader(pdf_path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        combined.append(f"--- Documento: {Path(pdf_path).name} ---\n{text}")
    return "\n\n".join(combined)


def _clone_repo(repo: str, target_dir: Path) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    subprocess.run(["gh", "repo", "clone", repo, str(target_dir)], check=True)


def _setup_cross_repo_workflow(project_dir: Path, repo: str, project_name: str, agent_repo: str) -> None:
    """
    Crea el workflow notify-oncall-agent.yml dentro del repo del proyecto
    y lo commitea/pushea alli mismo -- automatiza lo que antes se hacia
    a mano copiando el archivo de moto-chatbot-aws.
    """
    template_path = Path(__file__).resolve().parent / "templates" / "notify-oncall-agent.yml.tpl"
    template_text = template_path.read_text()
    content_yaml = template_text.replace("__AGENT_REPO__", agent_repo).replace("__PROJECT_NAME__", project_name)

    workflow_dir = project_dir / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (workflow_dir / "notify-oncall-agent.yml").write_text(content_yaml)

    subprocess.run(["git", "add", ".github/workflows/notify-oncall-agent.yml"], cwd=project_dir, check=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: notificar al Autonomous On-Call Engineer cuando este proyecto cambie"],
        cwd=project_dir, check=True,
    )
    subprocess.run(["git", "push", "origin", "main"], cwd=project_dir, check=True)

    token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(
        ["gh", "secret", "set", "CROSS_REPO_DISPATCH_TOKEN", "--repo", repo, "--body", token],
        check=True,
    )
    print(f"  Workflow y secret configurados en {repo}")


def _generate_terraform_snippet(project_name: str, log_group: str) -> Path:
    template_path = Path(__file__).resolve().parent / "templates" / "subscription_filter.tf.tpl"
    template_text = template_path.read_text()

    project_slug = project_name.replace("-", "_")
    statement_suffix = "".join(word.capitalize() for word in project_name.split("-"))

    content_tf = (
        template_text
        .replace("__PROJECT_SLUG__", project_slug)
        .replace("__PROJECT_STATEMENT__", statement_suffix)
        .replace("__LOG_GROUP__", log_group)
    )

    output_path = AGENT_ROOT / "infra" / "terraform" / f"generated_{project_slug}.tf"
    output_path.write_text(content_tf)
    return output_path


def _write_manifest(
    project_name: str,
    project_root: str,
    knowledge_base_path: str,
    log_group: str,
    repo: str,
    manifest_path: Path,
) -> None:
    content = f"""project:
  name: {project_name}
  root_path: {project_root}
  language: python

knowledge_base:
  path: {knowledge_base_path}

aws:
  region: us-east-1
  resource_tag:
    key: oncall-project
    value: {project_name}
  log_groups:
    - {log_group}

llm:
  hypothesis:
    provider: groq
    model: llama-3.3-70b-versatile
  escalation:
    provider: bedrock
    model: anthropic.claude-3-5-sonnet-20241022-v2:0
    region: us-east-1

notifications:
  channel: slack
  webhook_env_var: SLACK_WEBHOOK_URL

memory:
  postmortem_store_path: s3://{MEMORY_BUCKET}/{project_name}/postmortems.json

probe:
  s3_bucket: ""
  injected_payload: '{{esto no es json valido, sonda sintetica}}'
  injected_key_prefix: uploads/oncall-agent-probe

source:
  repo: {repo}
"""
    manifest_path.write_text(content)


AGENT_REPO = "giovany-desing/autonomous-oncall-engineer"


def onboard(
    repo: str,
    log_group: str,
    pdf_paths: list = None,
    local_path: str = None,
    setup_cross_repo: bool = True,
) -> None:
    project_name = repo.split("/")[-1]
    print(f"=== Onboarding de '{project_name}' (repo: {repo}) ===")

    if local_path:
        project_dir = Path(local_path)
        print(f"Usando carpeta local existente: {project_dir}")
    else:
        project_dir = Path(f"/tmp/onboard-{project_name}")
        print(f"Clonando {repo}...")
        _clone_repo(repo, project_dir)

    extra_context = ""
    if pdf_paths:
        print(f"Extrayendo texto de {len(pdf_paths)} PDF(s)...")
        extra_context = _extract_pdf_text(pdf_paths)
        print(f"  {len(extra_context)} caracteres extraidos")

    print("Corriendo onboarding (Tree-sitter + Groq)...")
    knowledge_base = build_knowledge_base(project_dir, extra_context=extra_context)

    kb_local_path = Path(f"/tmp/onboard-{project_name}-kb.json")
    save_knowledge_base(knowledge_base, kb_local_path)
    print(f"  {len(knowledge_base['funciones'])} funciones, "
          f"{len(knowledge_base['puntos_fragiles'])} puntos fragiles identificados")

    print("Subiendo base de conocimiento a S3...")
    subprocess.run([
        "aws", "s3", "cp", str(kb_local_path),
        f"s3://{MEMORY_BUCKET}/knowledge-bases/{project_name}/knowledge_base.json"
    ], check=True)

    manifest_path = AGENT_ROOT / "manifests" / f"{project_name}.yaml"
    print(f"Generando manifiesto: {manifest_path}")
    _write_manifest(
        project_name=project_name,
        project_root=str(project_dir),
        knowledge_base_path=str(kb_local_path),
        log_group=log_group,
        repo=repo,
        manifest_path=manifest_path,
    )

    print("Haciendo commit + push del manifiesto...")
    subprocess.run(["git", "add", str(manifest_path)], cwd=AGENT_ROOT.parent, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"feat: onboarding automatizado de {project_name}"],
        cwd=AGENT_ROOT.parent, check=True,
    )
    subprocess.run(["git", "push", "origin", "main"], cwd=AGENT_ROOT.parent, check=True)

    if setup_cross_repo and not local_path:
        print("Configurando workflow cross-repo en el proyecto...")
        _setup_cross_repo_workflow(project_dir, repo, project_name, AGENT_REPO)

    print("Generando bloque de Terraform para el subscription filter...")
    tf_path = _generate_terraform_snippet(project_name, log_group)
    print(f"  Generado en: {tf_path} (revisalo y corre terraform apply)")

    print()
    print("=== Onboarding completo. Pasos que TU debes confirmar manualmente: ===")
    print(f"1. Etiquetar los recursos de AWS de '{project_name}' con: oncall-project={project_name}")
    print(f"2. Si el proyecto necesita sonda sintetica, completar 'probe.s3_bucket' en {manifest_path}")
    print(f"3. Revisar el archivo Terraform generado: infra/terraform/generated_{project_name.replace('-', '_')}.tf")
    print(f"4. Correr 'terraform apply' en oncall-agent/infra/terraform")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Onboarding automatizado de un proyecto nuevo")
    parser.add_argument("--repo", required=True, help="owner/repo de GitHub")
    parser.add_argument("--log-group", required=True, help="Log group de CloudWatch")
    parser.add_argument("--pdf", action="append", default=[], help="Ruta a PDF de documentacion (repetible)")
    parser.add_argument("--local-path", default=None, help="Usar carpeta ya clonada en vez de clonar de nuevo")
    args = parser.parse_args()

    onboard(
        repo=args.repo,
        log_group=args.log_group,
        pdf_paths=args.pdf,
        local_path=args.local_path,
    )
