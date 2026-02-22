terraform {
       required_version = ">= 1.0"

       required_providers {
         aws = {
           source  = "hashicorp/aws"
           version = "~> 5.0"
         }
       }

       backend "s3" {
         bucket         = "thesis-pipeline-tfstate-767397977983"
         key            = "environments/dev/terraform.tfstate"
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

     module "network" {
       source = "../../modules/network"

       project_name       = var.project_name
       environment        = var.environment
       enable_nat_gateway = false
     }

     module "storage" {
       source = "../../modules/storage"

       project_name = var.project_name
       environment  = var.environment
     }

     module "monitoring" {
       source = "../../modules/monitoring"

       project_name          = var.project_name
       environment           = var.environment
       log_retention_days    = 7
       monthly_budget_amount = "50"
       alert_email           = var.alert_email
     }
