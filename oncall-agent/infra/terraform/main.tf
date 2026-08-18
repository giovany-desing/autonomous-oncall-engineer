terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

resource "aws_dynamodb_table" "incident_fingerprints" {
  name         = "oncall-agent-incident-fingerprints"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "fingerprint_id"

  attribute {
    name = "fingerprint_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    project = "oncall-agent"
  }
}

resource "aws_s3_bucket" "agent_memory" {
  bucket = "oncall-agent-memory-${data.aws_caller_identity.current.account_id}"

  tags = {
    project = "oncall-agent"
  }
}

resource "aws_s3_bucket" "lambda_deployments" {
  bucket = "oncall-agent-deployments-${data.aws_caller_identity.current.account_id}"

  tags = {
    project = "oncall-agent"
  }
}

resource "aws_iam_role" "agent_lambda_role" {
  name = "oncall-agent-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = {
    project = "oncall-agent"
  }
}

resource "aws_iam_role_policy_attachment" "agent_lambda_basic_execution" {
  role       = aws_iam_role.agent_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "agent_lambda_permissions" {
  name = "oncall-agent-permissions"
  role = aws_iam_role.agent_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "CloudWatchLogsRead"
        Effect   = "Allow"
        Action   = ["logs:FilterLogEvents", "logs:GetLogEvents"]
        Resource = "*"
      },
      {
        Sid      = "DynamoDBFingerprints"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:GetItem"]
        Resource = aws_dynamodb_table.incident_fingerprints.arn
      },
      {
        Sid      = "DynamoDBIncidentContext"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:GetItem"]
        Resource = aws_dynamodb_table.incident_context.arn
      },
      {
        Sid      = "DynamoDBCostLog"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.cost_log.arn
      },
      {
        Sid      = "DynamoDBEscalationBudget"
        Effect   = "Allow"
        Action   = ["dynamodb:UpdateItem", "dynamodb:GetItem"]
        Resource = aws_dynamodb_table.escalation_budget.arn
      },
      {
        Sid      = "S3Memory"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.agent_memory.arn}/*"
      },
      {
        Sid      = "S3MemoryListBucket"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.agent_memory.arn
      },
      {
        Sid      = "BedrockEscalation"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-5"
      },
      {
        Sid      = "ResourceDiscovery"
        Effect   = "Allow"
        Action   = ["tag:GetResources", "lambda:GetFunctionConfiguration"]
        Resource = "*"
      },
      {
        Sid      = "XRayRead"
        Effect   = "Allow"
        Action   = ["xray:GetTraceSummaries", "xray:BatchGetTraces"]
        Resource = "*"
      }
    ]
  })
}

resource "aws_lambda_function" "agent" {
  function_name = "oncall-agent-diagnosis"
  runtime       = "python3.12"
  handler       = "core.lambda_handler.lambda_handler"
  role          = aws_iam_role.agent_lambda_role.arn
  architectures = ["arm64"]
  timeout       = 90
  memory_size   = 512

  s3_bucket = aws_s3_bucket.lambda_deployments.id
  s3_key    = "agent.zip"

  environment {
    variables = {
      GROQ_API_KEY      = var.groq_api_key
      SLACK_WEBHOOK_URL = var.slack_webhook_url
      SLACK_BOT_TOKEN   = var.slack_bot_token
    }
  }

  tags = {
    project = "oncall-agent"
  }
}

resource "aws_lambda_permission" "allow_cloudwatch_logs" {
  statement_id  = "AllowCloudWatchLogsInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.agent.function_name
  principal     = "logs.us-east-1.amazonaws.com"
  source_arn    = "arn:aws:logs:us-east-1:531728396479:log-group:/aws/lambda/rag-demo-handler:*"
}

resource "aws_cloudwatch_log_subscription_filter" "rag_demo_errors" {
  name            = "oncall-agent-error-trigger"
  log_group_name  = "/aws/lambda/rag-demo-handler"
  filter_pattern  = "ERROR"
  destination_arn = aws_lambda_function.agent.arn

  depends_on = [aws_lambda_permission.allow_cloudwatch_logs]
}

resource "aws_lambda_function" "synthetic_probe" {
  function_name = "oncall-agent-synthetic-probe"
  runtime       = "python3.12"
  handler       = "probes.probe_handler.lambda_handler"
  role          = aws_iam_role.agent_lambda_role.arn
  architectures = ["arm64"]
  timeout       = 60
  memory_size   = 512

  s3_bucket = aws_s3_bucket.lambda_deployments.id
  s3_key    = "agent.zip"

  environment {
    variables = {
      GROQ_API_KEY      = var.groq_api_key
      SLACK_WEBHOOK_URL = var.slack_webhook_url
      SLACK_BOT_TOKEN   = var.slack_bot_token
    }
  }

  tags = {
    project = "oncall-agent"
  }
}

resource "aws_iam_role_policy" "probe_s3_write" {
  name = "oncall-agent-probe-s3-write"
  role = aws_iam_role.agent_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ProbeUploadWrite"
      Effect   = "Allow"
      Action   = ["s3:PutObject"]
      Resource = "arn:aws:s3:::rag-demo-uploads-531728396479/uploads/*"
    }]
  })
}

resource "aws_scheduler_schedule" "synthetic_probe_schedule" {
  name       = "oncall-agent-probe-schedule"
  group_name = "default"
  state      = "DISABLED" # Deshabilitada a proposito para no gastar Groq. Reactivar cuando se decida retomar la sonda.

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = "rate(15 minutes)"

  target {
    arn      = aws_lambda_function.synthetic_probe.arn
    role_arn = aws_iam_role.scheduler_role.arn
  }
}

resource "aws_iam_role" "scheduler_role" {
  name = "oncall-agent-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
    }]
  })

  tags = {
    project = "oncall-agent"
  }
}

resource "aws_iam_role_policy" "scheduler_invoke_lambda" {
  name = "oncall-agent-scheduler-invoke"
  role = aws_iam_role.scheduler_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = aws_lambda_function.synthetic_probe.arn
    }]
  })
}

resource "aws_sns_topic" "agent_self_monitoring" {
  name = "oncall-agent-self-monitoring"

  tags = {
    project = "oncall-agent"
  }
}

resource "aws_sns_topic_subscription" "self_monitoring_email" {
  topic_arn = aws_sns_topic.agent_self_monitoring.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "diagnosis_lambda_errors" {
  alarm_name          = "oncall-agent-diagnosis-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "El agente de diagnostico (oncall-agent-diagnosis) esta fallando -- el vigilante dejo de vigilar."
  alarm_actions       = [aws_sns_topic.agent_self_monitoring.arn]
  ok_actions          = [aws_sns_topic.agent_self_monitoring.arn]

  dimensions = {
    FunctionName = aws_lambda_function.agent.function_name
  }

  tags = {
    project = "oncall-agent"
  }
}

resource "aws_cloudwatch_metric_alarm" "probe_lambda_errors" {
  alarm_name          = "oncall-agent-synthetic-probe-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "La sonda sintetica (oncall-agent-synthetic-probe) esta fallando."
  alarm_actions       = [aws_sns_topic.agent_self_monitoring.arn]
  ok_actions          = [aws_sns_topic.agent_self_monitoring.arn]

  dimensions = {
    FunctionName = aws_lambda_function.synthetic_probe.function_name
  }

  tags = {
    project = "oncall-agent"
  }
}

resource "aws_lambda_permission" "allow_cloudwatch_logs_moto_api" {
  statement_id  = "AllowCloudWatchLogsInvokeMotoApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.agent.function_name
  principal     = "logs.us-east-1.amazonaws.com"
  source_arn    = "arn:aws:logs:us-east-1:531728396479:log-group:/aws/lambda/moto-chatbot-dev-api:*"
}

resource "aws_cloudwatch_log_subscription_filter" "moto_api_errors" {
  name            = "oncall-agent-error-trigger-moto-api"
  log_group_name  = "/aws/lambda/moto-chatbot-dev-api"
  filter_pattern  = "?ERROR ?WARNING ?\"Task timed out\""
  destination_arn = aws_lambda_function.agent.arn

  depends_on = [aws_lambda_permission.allow_cloudwatch_logs_moto_api]
}

resource "aws_lambda_permission" "allow_cloudwatch_logs_moto_worker" {
  statement_id  = "AllowCloudWatchLogsInvokeMotoWorker"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.agent.function_name
  principal     = "logs.us-east-1.amazonaws.com"
  source_arn    = "arn:aws:logs:us-east-1:531728396479:log-group:/aws/lambda/moto-chatbot-dev-worker:*"
}

resource "aws_cloudwatch_log_subscription_filter" "moto_worker_errors" {
  name            = "oncall-agent-error-trigger-moto-worker"
  log_group_name  = "/aws/lambda/moto-chatbot-dev-worker"
  filter_pattern  = "?ERROR ?WARNING ?\"Task timed out\""
  destination_arn = aws_lambda_function.agent.arn

  depends_on = [aws_lambda_permission.allow_cloudwatch_logs_moto_worker]
}

resource "aws_dynamodb_table" "incident_context" {
  name         = "oncall-agent-incident-context"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "thread_ts"

  attribute {
    name = "thread_ts"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    project = "oncall-agent"
  }
}

resource "aws_dynamodb_table" "cost_log" {
  name         = "oncall-agent-cost-log"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "incident_id"

  attribute {
    name = "incident_id"
    type = "S"
  }

  # Sin TTL a proposito: este es historico de costo que queremos
  # conservar para reportes FinOps, no datos efimeros de dedup.

  tags = {
    project = "oncall-agent"
  }
}

resource "aws_dynamodb_table" "escalation_budget" {
  name         = "oncall-agent-escalation-budget"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "hour_bucket"

  attribute {
    name = "hour_bucket"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    project = "oncall-agent"
  }
}



resource "aws_lambda_function" "slack_events" {
  function_name = "oncall-agent-slack-events"
  runtime       = "python3.12"
  handler       = "core.slack_events_handler.lambda_handler"
  role          = aws_iam_role.agent_lambda_role.arn
  architectures = ["arm64"]
  timeout       = 120
  memory_size   = 512

  s3_bucket = aws_s3_bucket.lambda_deployments.id
  s3_key    = "agent.zip"

  environment {
    variables = {
      GROQ_API_KEY         = var.groq_api_key
      SLACK_BOT_TOKEN      = var.slack_bot_token
      SLACK_SIGNING_SECRET = var.slack_signing_secret
    }
  }

  tags = {
    project = "oncall-agent"
  }
}

resource "aws_apigatewayv2_api" "slack_events_api" {
  name          = "oncall-agent-slack-events-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "slack_events_integration" {
  api_id                 = aws_apigatewayv2_api.slack_events_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.slack_events.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "slack_events_route" {
  api_id    = aws_apigatewayv2_api.slack_events_api.id
  route_key = "POST /slack/events"
  target    = "integrations/${aws_apigatewayv2_integration.slack_events_integration.id}"
}

resource "aws_apigatewayv2_stage" "slack_events_stage" {
  api_id      = aws_apigatewayv2_api.slack_events_api.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "allow_apigateway_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.slack_events.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.slack_events_api.execution_arn}/*/*"
}

output "slack_events_endpoint" {
  value = "${aws_apigatewayv2_api.slack_events_api.api_endpoint}/slack/events"
}
