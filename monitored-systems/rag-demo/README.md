# rag-demo

Sistema de ingesta y validación de documentos para un pipeline de RAG.

## Qué hace

Cuando un usuario sube un documento JSON a un bucket de S3, una Lambda
(`lambda/handler.py`) se dispara automáticamente vía evento de S3, descarga
el archivo, valida que tenga la estructura esperada, y lo deja listo para
ser indexado en el paso siguiente del pipeline (fuera del alcance de este
repo).

## Flujo

1. Un cliente externo sube un archivo `.json` a un bucket S3 (prefijo
   `uploads/`).
2. El evento `s3:ObjectCreated` dispara `lambda_handler`.
3. `process_upload` descarga el objeto desde S3 y parsea su contenido.
4. `validate_and_store` valida que el documento tenga el campo `user_id`.
   Si el documento es válido, se marca como listo para indexación.
5. Si algo falla durante la descarga o el parseo, actualmente no se
   registra ningún log (ver sección de limitaciones conocidas).

## Infraestructura

- **Cómputo**: AWS Lambda (Python 3.12)
- **Storage**: S3 (bucket de uploads)
- **Trigger**: S3 Event Notification → Lambda

## Dependencias externas

- Amazon S3 (lectura del documento subido)

## Limitaciones conocidas

- `process_upload` captura cualquier excepción durante la descarga/parseo
  sin registrar el error ni relanzarlo. Si S3 lanza un `ThrottlingException`
  o el JSON viene malformado, la función retorna silenciosamente sin dejar
  rastro — este es un punto ciego conocido, pendiente de corregir.
- No hay reintentos configurados para las llamadas a S3.
- No hay métricas ni alarmas de CloudWatch configuradas todavía.
