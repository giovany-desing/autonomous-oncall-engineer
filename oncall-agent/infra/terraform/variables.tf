variable "aws_region" {
  description = "Región de AWS donde se despliega la infraestructura del agente"
  type        = string
  default     = "us-east-1"
}

variable "groq_api_key" {
  description = "API key de Groq para el nodo Hipotesis"
  type        = string
  sensitive   = true
}

variable "slack_webhook_url" {
  description = "Webhook de Slack para notificaciones"
  type        = string
  sensitive   = true
}

variable "alert_email" {
  description = "Correo para alertas cuando el propio agente falla"
  type        = string
}

variable "slack_bot_token" {
  description = "Bot Token de Slack para chat.postMessage y responder en hilos"
  type        = string
  sensitive   = true
}

variable "slack_signing_secret" {
  description = "Signing Secret de Slack para verificar que los eventos son legitimos"
  type        = string
  sensitive   = true
}
