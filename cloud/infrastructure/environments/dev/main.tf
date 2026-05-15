terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }

  backend "s3" {
    bucket         = "thesis-pipeline-tfstate-767397977983"
    key            = "cloud/dev/terraform.tfstate"
    region         = "eu-central-1"
    dynamodb_table = "thesis-pipeline-tflock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "terraform_remote_state" "base" {
  backend = "s3"
  config = {
    bucket = "thesis-pipeline-tfstate-767397977983"
    key    = "environments/dev/terraform.tfstate"
    region = "eu-central-1"
  }
}

data "aws_vpc" "main" {
  id = data.terraform_remote_state.base.outputs.vpc_id
}

data "aws_security_groups" "vpc_internal" {
  filter {
    name   = "vpc-id"
    values = [data.terraform_remote_state.base.outputs.vpc_id]
  }
  filter {
    name   = "tag:Name"
    values = ["*vpc-internal*"]
  }
}

data "aws_s3_bucket" "data_lake" {
  bucket = data.terraform_remote_state.base.outputs.data_lake_bucket_name
}

locals {
  data_lake_bucket = data.terraform_remote_state.base.outputs.data_lake_bucket_name
}

module "ses" {
  source = "../../modules/ses"

  project_name = var.project_name
  environment  = var.environment
  alert_email  = var.alert_email
  aws_region   = var.aws_region
}
