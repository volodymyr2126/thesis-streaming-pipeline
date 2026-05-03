variable "project_name" { type = string }
variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "vpc_cidr" { type = string }

variable "private_subnet_ids" {
  type        = list(string)
  description = "At least two subnets in different AZs for MSK broker placement"
}