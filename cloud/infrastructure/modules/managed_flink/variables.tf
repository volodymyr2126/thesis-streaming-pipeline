variable "project_name" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "kafka_bootstrap" { type = string }
variable "msk_cluster_arn" { type = string }
variable "data_lake_bucket_name" { type = string }
variable "data_lake_bucket_arn" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "vpc_internal_sg_id" { type = string }

variable "rds_host" {
  type    = string
  default = ""
}

variable "rds_db" {
  type    = string
  default = ""
}

variable "rds_user" {
  type    = string
  default = ""
}

variable "rds_password_secret_arn" {
  type    = string
  default = ""
}
