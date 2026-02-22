variable "vpc_cidr" {
       description = "CIDR block for VPC"
       type        = string
       default     = "10.0.0.0/16"
     }

     variable "public_subnet_cidrs" {
       description = "CIDR blocks for public subnets"
       type        = list(string)
       default     = ["10.0.1.0/24", "10.0.2.0/24"]
     }

     variable "private_subnet_cidrs" {
       description = "CIDR blocks for private subnets"
       type        = list(string)
       default     = ["10.0.10.0/24", "10.0.11.0/24"]
     }

     variable "availability_zones" {
       description = "Availability zones"
       type        = list(string)
       default     = ["eu-central-1a", "eu-central-1b"]
     }

     variable "enable_nat_gateway" {
       description = "Whether to create a NAT Gateway (costs ~$32/month)"
       type        = bool
       default     = false
     }

     variable "project_name" {
       description = "Project name for resource naming"
       type        = string
     }

     variable "environment" {
       description = "Environment name (dev, staging, prod)"
       type        = string
     }
