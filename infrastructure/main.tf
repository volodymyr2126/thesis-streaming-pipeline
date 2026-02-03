terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "thesis-terraform-state-vm-1231"
    key            = "streaming-pipeline/terraform.tfstate"
    region         = "eu-west-1"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "thesis-streaming-pipeline"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

resource "aws_cloudwatch_log_group" "pipeline_logs" {
  name              = "/aws/streaming-pipeline/${var.environment}"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${var.project_name}-logs"
  }
}

resource "aws_s3_bucket" "data_lake" {
  bucket = "${var.project_name}-data-lake-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "${var.project_name}-data-lake"
  }
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  rule {
    id     = "delete-incomplete-multipart"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_caller_identity" "current" {}
