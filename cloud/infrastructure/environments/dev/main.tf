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

# ── Re-use shared network and storage from the base environment ───────────────

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
  vpc_id             = data.terraform_remote_state.base.outputs.vpc_id
  vpc_cidr           = data.aws_vpc.main.cidr_block
  public_subnet_ids  = data.terraform_remote_state.base.outputs.public_subnet_ids
  private_subnet_ids = data.terraform_remote_state.base.outputs.private_subnet_ids
  vpc_internal_sg_id = data.aws_security_groups.vpc_internal.ids[0]
  data_lake_bucket   = data.terraform_remote_state.base.outputs.data_lake_bucket_name
  data_lake_arn      = data.aws_s3_bucket.data_lake.arn
}

# ── MSK (Kafka) ───────────────────────────────────────────────────────────────

module "msk" {
  source = "../../modules/msk"

  project_name       = var.project_name
  environment        = var.environment
  vpc_id             = local.vpc_id
  vpc_cidr           = local.vpc_cidr
  private_subnet_ids = local.private_subnet_ids
}

# ── SES ───────────────────────────────────────────────────────────────────────

module "ses" {
  source = "../../modules/ses"

  project_name = var.project_name
  environment  = var.environment
  alert_email  = var.alert_email
  aws_region   = var.aws_region
}
