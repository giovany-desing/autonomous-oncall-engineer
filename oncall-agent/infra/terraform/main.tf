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
    enabled         = true
  }

  tags = {
    project = "oncall-agent"
  }
}
