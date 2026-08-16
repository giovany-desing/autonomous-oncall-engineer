Autonomous On-Call Engineer

Sistema de SRE autónomo que monitorea proyectos desplegados en AWS, diagnostica incidentes correlacionando código real, logs, infraestructura y trazas, notifica en Slack con causa raíz y solución propuesta, y sostiene una conversación de seguimiento en el hilo de la notificación — con acceso de lectura real al código y la infraestructura del proyecto, no solo al resumen congelado del diagnóstico original.
Nunca ejecuta ni modifica nada de forma autónoma. Solo diagnostica, propone, y conversa. Esa restricción es una decisión de diseño deliberada, no una limitación técnica.


1. Problema
Cuando un sistema en producción falla, el tiempo más caro no es arreglar el problema — es entenderlo:
Los logs rara vez dicen "aquí está la causa raíz"; hay que correlacionar manualmente el log con el código que lo generó.
Los errores silenciosos (excepciones capturadas sin logging) no dejan ningún rastro que un sistema de alertas tradicional pueda detectar.
Un desarrollador nuevo en el equipo, o alguien de guardia a las 3 AM, no tiene el contexto completo del proyecto en la cabeza.
Las herramientas comerciales de diagnóstico automático son caras, generalistas, y no explican su razonamiento con evidencia verificable.


2. Solución
Un agente que:
Vigila 24/7 — reactivamente (CloudWatch Logs Subscription Filter) y proactivamente (sondas sintéticas que inyectan fallos conocidos para detectar puntos ciegos que nunca generan un log de error).
Diagnostica con evidencia real — un pipeline de 4 agentes (LangGraph) que recolecta logs + código + infraestructura + trazas, genera hipótesis rankeadas, las valida contra memoria de incidentes pasados, y calibra un nivel de confianza honesto.
Evita gastar dinero en ruido — deduplicación por fingerprint antes de correr cualquier diagnóstico costoso.
Notifica con transparencia — causa probable, solución propuesta, evidencia usada, y el costo exacto en dólares de esa investigación puntual (típicamente $0.0005–$0.0015 USD).
Conversa como un ingeniero senior con acceso real al repo — responde preguntas de seguimiento en el hilo de Slack, explorando activamente el código fuente completo, la estructura del proyecto, la infraestructura real de AWS, y logs en tiempo real — con memoria de la conversación en curso.
Se despliega y se conoce a sí mismo automáticamente — CI/CD redespliega el sistema cuando su propio código cambia, y actualiza el conocimiento de cada proyecto monitoreado cuando ESE proyecto cambia.
Escala a múltiples proyectos sin tocar código — agregar un proyecto nuevo es un manifiesto YAML + tags de AWS.
3. Arquitectura — flujo end-to-end
CloudWatch Logs (ERROR/WARNING/timeout)
        │
        ▼
Subscription Filter ──► Lambda: oncall-agent-diagnosis
        │                       ├─ 1. Fingerprint check (DynamoDB) → si es duplicado, se descarta aquí
        │                       ▼
        │               Grafo LangGraph (4 nodos):
        │               Recolector → Hipótesis (Groq, escala a Bedrock si es ambiguo)
        │                         → Validador (cruza con memoria de postmortems, S3)
        │                         → Comunicador (chat.postMessage a Slack, guarda contexto en DynamoDB)
        ▼
Slack: notificación en el canal, con hilo propio
        │  (el desarrollador responde en el hilo)
        ▼
Slack Events API ──► API Gateway ──► Lambda: oncall-agent-slack-events
                                            ├─ Carga contexto del incidente (DynamoDB)
                                            ├─ Carga historial de la conversación (mismo registro)
                                            ├─ Tool calling con Groq (hasta 8 rondas):
                                            │     - leer_archivo (S3, código fuente real)
                                            │     - listar_archivos (S3, estructura real)
                                            │     - buscar_en_codigo (base de conocimiento)
                                            │     - consultar_infraestructura (AWS real)
                                            │     - consultar_logs_recientes (CloudWatch en vivo)
                                            └─ Responde en el hilo, guarda el turno en el historial

EventBridge Scheduler (cada 15 min) ──► Lambda: oncall-agent-synthetic-probe
                                              ├─ Inyecta un payload malformado conocido
                                              ├─ Verifica si CloudWatch registró algún error
                                              └─ Si NO hay evidencia → dispara el mismo pipeline de diagnóstico

CI/CD (GitHub Actions):
  push a oncall-agent/**          ──► redeploy de las 3 Lambdas
  push a un repo externo          ──► repository_dispatch ──► reonboarding de ESE proyecto
  cada ejecución                  ──► corre pytest → empaqueta → despliega → smoke test post-deploy
4. Estructura de archivos y rol de cada uno
autonomous-oncall-engineer/
│
├── .github/workflows/
│   └── deploy-agent.yml          # CI/CD: tests → onboarding del proyecto disparador → sube código
│                                  # fuente a S3 → descarga TODAS las bases de conocimiento existentes →
│                                  # empaqueta → despliega 3 Lambdas → smoke test post-deploy
│
├── monitored-systems/
│   └── rag-demo/                 # Proyecto de prueba interno (vive en este mismo repo)
│       ├── lambda/handler.py     # Lambda de ejemplo con un bug real (except: pass)
│       └── terraform/            # Infraestructura del proyecto de prueba
│
└── oncall-agent/                 # El agente en sí
    │
    ├── core/                     # Orquestación central
    │   ├── state.py              # DiagnosisState: esquema de datos que viaja entre los 4 nodos del grafo
    │   ├── config.py             # Carga y valida manifiestos YAML, resuelve rutas (local, S3, absoluta)
    │   ├── registry.py           # Mapea log_group → proyecto/manifiesto, habilita multi-proyecto
    │   ├── graph.py               # Ensambla los 4 agentes en el grafo de LangGraph
    │   ├── entrypoint.py          # Punto de entrada real: fingerprint check → run_diagnosis
    │   ├── lambda_handler.py      # Handler de diagnóstico: decodifica evento CloudWatch, resuelve
    │   │                          # proyecto vía registry, llama a entrypoint
    │   ├── slack_events_handler.py # Handler conversacional: verifica firma de Slack, carga contexto +
    │   │                          # historial, tool calling con Groq, responde en el hilo
    │   ├── agent_tools.py         # Las 5 herramientas reales del chat
    │   │
    │   └── agents/                # Los 4 nodos del grafo de diagnóstico
    │       ├── collector.py       # Orquesta los 4 adaptadores, sin LLM
    │       ├── hypothesis.py      # Genera hipótesis vía Groq; escala a Bedrock si confianza < 0.6 o ambigüedad
    │       ├── validator.py       # Cruza hipótesis con memoria de postmortems, calibra confianza final
    │       └── communicator.py    # Formatea mensaje, envía a Slack (Bot Token), guarda contexto en DynamoDB
    │
    ├── adapters/                  # Conectores a fuentes de evidencia real
    │   ├── cloudwatch_adapter.py  # Consulta logs por ventana de tiempo (filter_log_events)
    │   ├── code_adapter.py        # Búsqueda exacta y por palabra clave sobre la base de conocimiento
    │   ├── aws_resource_adapter.py # Descubre recursos por tag, trae config de Lambda
    │   └── external_connection_adapter.py # Latencia/errores de dependencias externas vía X-Ray
    │
    ├── dedup/
    │   └── fingerprint.py         # Hash normalizado (UUIDs/timestamps → placeholders), registro
    │                              # atómico en DynamoDB para evitar diagnósticos duplicados
    │
    ├── memory/
    │   └── postmortem_store.py    # Memoria de incidentes resueltos en S3 (JSON + similitud de coseno)
    │                              # DEUDA TÉCNICA: embedding es hash placeholder, no semántico real
    │
    ├── onboarding/                 # Todo lo que analiza un proyecto nuevo o actualizado
    │   ├── structural_scan.py     # Pasada 1: Tree-sitter cataloga funciones, clasifica riesgo de
    │   │                          # manejo de errores, captura código fuente real, excluye build/deps
    │   ├── architecture_summary.py # Pasada 2: Groq genera resumen de arquitectura + puntos frágiles
    │   ├── risk_map.py             # Combina Pasadas 1+2 en la base de conocimiento persistida
    │   ├── generate_lambda_manifest.py # Genera manifiesto de Lambda ajustando rutas automáticamente
    │   ├── extract_source_repo.py # Lee source.repo de un manifiesto (usado por CI/CD)
    │   ├── upload_source_to_s3.py # Sube código fuente completo a S3 para el chat conversacional
    │   ├── onboard_project.py     # Wizard: clona → onboarding → S3 → manifiesto → commit+push →
    │   │                          # workflow cross-repo → bloque de Terraform, todo en un comando
    │   └── templates/              # Plantillas usadas por el wizard
    │
    ├── probes/
    │   ├── synthetic_probe.py     # Inyecta payload conocido, verifica evidencia en CloudWatch
    │   └── probe_handler.py       # Itera sobre TODOS los proyectos registrados con sonda configurada
    │
    ├── manifests/                  # Un YAML por proyecto (fuente de verdad; *-lambda.yaml es generado, no se versiona)
    │
    ├── infra/terraform/            # Infraestructura completa: DynamoDB, S3, 3 Lambdas, IAM,
    │   │                            # subscription filters, API Gateway, EventBridge Scheduler, alarmas
    │   └── terraform.tfvars        # Secretos reales — NUNCA se versiona
    │
    ├── tests/
    │   ├── test_fingerprint.py, test_agent_tools.py, test_code_adapter.py,
    │   │   test_slack_events_handler.py, test_structural_scan.py   # 22 tests cubriendo bugs reales
    │   ├── eval_dataset.json       # 4 casos reales con ground truth conocido
    │   ├── run_evaluation.py       # Corre el sistema real contra el dataset
    │   └── smoke_test_post_deploy.py # Invoca las 3 Lambdas reales tras cada deploy
    │
    ├── requirements.txt
    └── pytest.ini
5. Stack tecnológico
Capa	Tecnología	Notas
Cómputo	AWS Lambda, arm64 (Graviton)	3 funciones: diagnosis, synthetic-probe, slack-events
Orquestación de agentes	LangGraph	4 nodos con estado compartido (DiagnosisState)
LLM — hipótesis rápida	Groq (llama-3.3-70b-versatile)	Barato; límite de 100k tokens/día en el tier usado
LLM — escalamiento	AWS Bedrock (anthropic.claude-sonnet-5)	Requiere habilitar acceso al modelo en Bedrock Model Access
Análisis de código	Tree-sitter (+ tree-sitter-language-pack)	Captura AST, riesgo de manejo de errores, código fuente real
Disparo en tiempo real	CloudWatch Logs Subscription Filter	Patrón ?ERROR ?WARNING ?"Task timed out"
Disparo proactivo	EventBridge Scheduler (cada 15 min)	Sondas sintéticas
Estado / dedup	DynamoDB (on-demand)	incident-fingerprints, incident-context (con TTL)
Memoria de código y postmortems	S3	source-code/, knowledge-bases/, memoria de postmortems
Notificación y chat	Slack Bot Token (chat.postMessage) + Slack Events API	Bot Token en vez de webhook, para soportar hilos
Endpoint conversacional	API Gateway (HTTP API) + Lambda	Verificación de firma HMAC de Slack
Infraestructura como código	Terraform	State local (deuda técnica: debería ser remoto)
CI/CD	GitHub Actions	Trigger push y repository_dispatch cross-repo
Testing	pytest	22 tests unitarios + smoke test + evaluación con ground truth
Descubrimiento de infraestructura	boto3 + Resource Groups Tagging API	Genérico por tag
Trazas de dependencias externas	AWS X-Ray	Requiere SDK instrumentado en el proyecto monitoreado
PDFs de documentación	pypdf	Contexto adicional opcional en el onboarding
6. Gaps conocidos — lo que falta implementar
MLOps
Embeddings semánticos reales: hoy es un hash placeholder. Bloqueado dos veces por cuota 0 de Titan Embeddings en Bedrock (requiere solicitud de aumento de cuota en AWS Service Quotas — trámite externo, no un bug de código).
Tracking de experimentos (MLflow/DVC): nunca implementado.
Dataset de evaluación: existe (eval_dataset.json, 4 casos), pero pequeño y no cubre el chat conversacional, solo el diagnóstico automático.
Métricas agregadas de calidad: no hay dashboard histórico.
CI/CD
Terraform state local: riesgo real de pérdida de control de infraestructura; debería migrarse a S3 + lock de DynamoDB.
Sin ambiente de staging: todo cambio va directo a producción.
Sin versionado de Lambda ($LATEST siempre): sin rollback rápido.
terraform apply sigue siendo manual: CI/CD no aplica infraestructura, solo código.
Sin revisión de PR: todo el desarrollo fue push directo a main.
Capacidades del chat conversacional
Multi-proyecto en la misma conversación: cada hilo está atado permanentemente al proyecto del incidente original.
Proponer cambios como Pull Request real: hoy solo sugiere código en texto; la versión segura de "modificar" sería generar un PR real vía API de GitHub para revisión humana — nunca ejecución directa.
Groq (Llama 3.3) genera ocasionalmente sintaxis de tool-calling malformada de forma reproducible para ciertas preguntas — mitigado con reintentos de estrategia y sanitización del historial, no eliminado de raíz.
Seguridad
Algunos permisos IAM más amplios de lo ideal (Resource: "*" en lectura de logs, descubrimiento de recursos, X-Ray).
Secretos en variables de entorno de Lambda, no en Secrets Manager.
Endpoint de Slack Events sin rate limiting propio más allá de la verificación de firma.
Alcance
Solo gramática de Tree-sitter validada en la práctica para Python.
Sin detección de llamadas externas para Redis/RDS directas.
Un solo ambiente/cuenta de AWS, sin separación dev/staging/prod.
7. Principio de diseño no negociable
El sistema nunca ejecuta ni modifica nada por sí mismo. Diagnostica, propone, y conversa. Cualquier capacidad futura de "aplicar" un fix debe pasar por una propuesta explícita (ej. un Pull Request) que un humano revise y apruebe — nunca una acción directa contra producción.
ok, falta contenido para el readme?
Sí, faltan algunas secciones que serían útiles para que el README esté realmente completo como documentación de referencia — te las detallo, y tú decides cuáles quieres que agregue:
Lo que no incluí y valdría la pena agregar
Guía de setup/instalación — cómo alguien nuevo (o tú en 6 meses) levantaría este proyecto desde cero: clonar, pip install -r requirements.txt, variables de entorno necesarias (GROQ_API_KEY, SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, etc.), terraform init/apply.
Guía de onboarding de un proyecto nuevo — el comando exacto (onboard_project.py) y los pasos manuales que quedan (etiquetar recursos, revisar el .tf generado, terraform apply) — ya lo explicamos en el chat hoy pero nunca quedó en el README.
Costos reales medidos — los números concretos que confirmamos con Cost Explorer (CloudWatch $0, diagnóstico individual $0.0005–$0.0015, etc.) — le da credibilidad real al README en vez de solo afirmaciones.
Tabla de variables de entorno y secretos — qué necesita cada Lambda, dónde se configuran (Terraform vars vs GitHub Secrets), para que no se repita el problema de "cambios aplicados manualmente sin documentar".
Comandos de operación diaria — cómo ver logs de cada Lambda, cómo correr los tests, cómo correr la evaluación, cómo pausar/reactivar la sonda sintética.
Historial de decisiones de arquitectura (ADR resumido) — por qué LangGraph y no Step Functions, por qué Bot Token y no webhook, por qué S3 para código fuente y no empaquetado en el zip — decisiones que hoy solo existen en esta conversación, no en ningún documento.
Changelog o línea de tiempo — qué se construyó en qué sesión, útil si el proyecto sigue creciendo y quieres saber "¿cuándo agregamos la sonda sintética?" sin buscar en el historial de git commit por commit.
¿Cuáles de estas quieres que agregue? Puedo hacerlas todas o las que priorices.
Suministrame lo que no incluiste
Guía de setup/instalación
zsh
# 1. Clonar y preparar el entorno
git clone https://github.com/giovany-desing/autonomous-oncall-engineer.git
cd autonomous-oncall-engineer/oncall-agent
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Variables de entorno locales (.env, nunca se versiona)
cat > .env << 'EOF'
GROQ_API_KEY=gsk_...
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...   # legado, ya no se usa activamente
EOF

# 3. Terraform
cd infra/terraform
terraform init
cat > terraform.tfvars << 'EOF'
groq_api_key      = "gsk_..."
slack_webhook_url = "https://hooks.slack.com/services/..."
slack_bot_token   = "xoxb-..."
slack_signing_secret = "..."
alert_email       = "tu-correo@ejemplo.com"
EOF
terraform plan
terraform apply
Prerequisitos externos (no automatizables desde código):
App de Slack creada en api.slack.com, con Bot Token (chat:write, channels:history, channels:read), Signing Secret, Socket Mode desactivado, Event Subscriptions apuntando al endpoint de API Gateway, suscrito a message.channels.
Bot invitado al canal de notificaciones (/invite @nombre-del-bot).
Acceso habilitado en Bedrock Model Access para el modelo de escalamiento (anthropic.claude-sonnet-5).
gh (GitHub CLI) autenticado, con secrets configurados en el repo: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, GROQ_API_KEY, CROSS_REPO_CLONE_TOKEN.
Guía de onboarding de un proyecto nuevo
zsh
python onboarding/onboard_project.py \
  --repo owner/nombre-del-repo \
  --log-group /aws/lambda/nombre-handler \
  [--pdf documentacion.pdf] \
  [--local-path /ruta/si/ya/esta/clonado]
Automatiza: clonar → extraer PDFs (opcional) → Tree-sitter + Groq → subir base de conocimiento y código fuente a S3 → generar manifiesto → commit + push → configurar workflow cross-repo + secret → generar bloque de Terraform del subscription filter.
Pasos manuales que quedan, con intención (requieren tu criterio):
Etiquetar los recursos de AWS reales: oncall-project=<nombre-proyecto>.
Completar probe.s3_bucket en el manifiesto si el proyecto necesita sonda sintética.
Revisar el .tf generado (infra/terraform/generated_<proyecto>.tf).
terraform apply.
Costos reales medidos (confirmados con AWS Cost Explorer)
Componente	Costo medido
CloudWatch (logs, alarmas, subscription filters)	$0.00 (dentro del free tier)
Diagnóstico individual (Groq only)	$0.0005 – $0.0015 USD
Diagnóstico con escalamiento a Bedrock	mayor, no medido aún en producción real
Lambda (las 3 funciones, todo el tráfico de pruebas)	~$0.00
DynamoDB (on-demand)	~$0.000008
S3 (memoria + código fuente + deployments)	~$0.001
Bedrock (Titan/Claude, uso puntual)	~$0.001
El riesgo de costo originalmente identificado (CloudWatch Logs Insights) nunca se materializó porque el sistema usa filter_log_events, no Logs Insights.
Variables de entorno y secretos por componente
Variable	Dónde vive	Usada por
GROQ_API_KEY	Terraform var + GitHub Secret	Las 3 Lambdas, CI/CD (onboarding)
SLACK_BOT_TOKEN	Terraform var	oncall-agent-diagnosis, oncall-agent-synthetic-probe, oncall-agent-slack-events
SLACK_SIGNING_SECRET	Terraform var	oncall-agent-slack-events (verificación de firma)
SLACK_WEBHOOK_URL	Terraform var	Legado, ya no se usa activamente
AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY	GitHub Secrets	CI/CD
CROSS_REPO_CLONE_TOKEN	GitHub Secret (repo del agente)	CI/CD, para clonar repos externos
CROSS_REPO_DISPATCH_TOKEN	GitHub Secret (cada repo externo)	Workflow del proyecto externo, para avisar al agente
Comandos de operación diaria
zsh
# Logs de cada Lambda
aws logs tail /aws/lambda/oncall-agent-diagnosis --since 15m
aws logs tail /aws/lambda/oncall-agent-slack-events --since 15m
aws logs tail /aws/lambda/oncall-agent-synthetic-probe --since 15m

# Tests
cd oncall-agent && python -m pytest tests/ -v

# Evaluación con ground truth
python tests/run_evaluation.py

# Smoke test manual
python tests/smoke_test_post_deploy.py

# Pausar / reactivar la sonda sintética
aws scheduler update-schedule --name oncall-agent-probe-schedule --group-name default \
  --schedule-expression "rate(15 minutes)" --flexible-time-window "Mode=OFF" \
  --target "$(aws scheduler get-schedule --name oncall-agent-probe-schedule --group-name default --query 'Target' --output json)" \
  --state DISABLED   # o ENABLED

# Redespliegue manual completo (sin pasar por CI/CD)
cd oncall-agent/infra/terraform && terraform apply
Decisiones de arquitectura (ADR resumido)
Decisión	Alternativa considerada	Por qué se eligió así
LangGraph para orquestar los 4 agentes	AWS Step Functions	El flujo tiene ramas reales (escalamiento a Bedrock, calibración de confianza); Step Functions daría auditoría gratis pero LangGraph ya estaba validado y ofrece portabilidad fuera de AWS
Bot Token de Slack (chat.postMessage)	Incoming Webhook	El webhook no devuelve thread_ts, imposible sostener conversación en hilo
Código fuente en S3, no empaquetado en el zip de Lambda	Incluir el repo completo en cada deploy	El zip ya pesaba 24MB; S3 permite que el chat vea siempre la versión más reciente sin reempaquetar
CloudWatch filter_log_events, no Logs Insights	Logs Insights (más potente)	Insights cobra por GB escaneado; con el volumen esperado, el riesgo de costo no valía la potencia extra
Fingerprinting con DynamoDB ConditionExpression	Verificar existencia + escribir en dos pasos	Atómico, validado con 10 hilos concurrentes sin condición de carrera
Manifiesto de Lambda generado, no versionado a mano	Mantener dos YAMLs sincronizados manualmente	Ya causó bugs reales (rutas desincronizadas); una sola fuente de verdad (el manifiesto base)
arm64/Graviton en todas las Lambdas	x86_64	~20% más barato, sin cambios de código para Python
Línea de tiempo (resumen de hitos)
Diseño inicial del documento de arquitectura, revisión crítica de viabilidad.
MVP local: onboarding (Tree-sitter + Groq), 4 adaptadores, grafo de 4 agentes — validado contra rag-demo real.
Despliegue en Lambda real, subscription filter, primer incidente diagnosticado de forma 100% autónoma.
Limitantes atacadas: auto-monitoreo, CI/CD, manifiestos unificados, namespacing multi-proyecto, prueba de concurrencia, costo real confirmado en $0.
Incorporación de moto-chatbot como segundo proyecto real — reveló y corrigió: filtro de logs muy estrecho, permiso de S3 faltante, logging insuficiente.
Automatización del onboarding: CI/CD generalizado (sin if por proyecto), wizard onboard_project.py de un solo comando.
Conversación en hilo de Slack: Bot Token, DynamoDB de contexto, Slack Events API — corrigiendo en el camino Socket Mode, dotenv corrupto (dos veces), permisos IAM faltantes, reintentos duplicados de Slack.
Chat con herramientas reales tipo Claude Code: lectura de archivo completo, navegación de estructura, infraestructura real, todo sincronizado vía CI/CD — corrigiendo rutas mal generadas y respuestas malformadas del LLM.
Memoria de conversación en el hilo, logs en tiempo real como herramienta.
Infraestructura de testing: 22 tests unitarios, smoke test post-deploy, dataset de evaluación con ground truth — descubriendo en el proceso que el workflow nunca desplegaba una de las tres Lambdas, y que el modelo de Bedrock configurado había llegado a fin de vida.






