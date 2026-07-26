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
