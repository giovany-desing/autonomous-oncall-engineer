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
        Sid      = "S3Memory"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.agent_memory.arn}/*"
      },
      {
        Sid      = "BedrockEscalation"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
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
