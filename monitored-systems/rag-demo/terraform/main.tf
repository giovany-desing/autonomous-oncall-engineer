terraform {
  required_version = ">= 1.5"
  required_providers {
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
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

resource "aws_s3_bucket" "uploads" {
  bucket = "rag-demo-uploads-${data.aws_caller_identity.current.account_id}"

  tags = {
    oncall-project = "rag-demo"
  }
}

resource "aws_iam_role" "lambda_role" {
  name = "rag-demo-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = {
    oncall-project = "rag-demo"
  }
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_xray" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy" "lambda_s3_read" {
  name = "rag-demo-s3-read"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "${aws_s3_bucket.uploads.arn}/*"
    }]
  })
}

resource "null_resource" "install_dependencies" {
  triggers = {
    requirements_hash = filesha256("${path.module}/../lambda/requirements.txt")
    handler_hash      = filesha256("${path.module}/../lambda/handler.py")
  }

  provisioner "local-exec" {
    command = <<-EOT
      rm -rf ${path.module}/build/package
      mkdir -p ${path.module}/build/package
      cp ${path.module}/../lambda/handler.py ${path.module}/build/package/
      pip install \
        aws-xray-sdk==2.14.0 \
        --no-deps \
        --target ${path.module}/build/package \
        --platform manylinux2014_aarch64 \
        --python-version 3.12 \
        --only-binary=:all: \
        --upgrade
      pip install \
        wrapt \
        --target ${path.module}/build/package \
        --platform manylinux2014_aarch64 \
        --python-version 3.12 \
        --only-binary=:all: \
        --upgrade
    EOT
  }
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/build/package"
  output_path = "${path.module}/build/handler.zip"

  depends_on = [null_resource.install_dependencies]
}

resource "aws_lambda_function" "handler" {
  function_name    = "rag-demo-handler"
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  role             = aws_iam_role.lambda_role.arn
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  architectures    = ["arm64"]
  timeout          = 30

  tracing_config {
    mode = "Active"
  }

  tags = {
    oncall-project = "rag-demo"
  }
}

resource "aws_lambda_permission" "allow_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.handler.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.uploads.arn
}

resource "aws_s3_bucket_notification" "trigger" {
  bucket = aws_s3_bucket.uploads.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.handler.arn
    events               = ["s3:ObjectCreated:*"]
    filter_prefix        = "uploads/"
    filter_suffix        = ".json"
  }

  depends_on = [aws_lambda_permission.allow_s3]
}
