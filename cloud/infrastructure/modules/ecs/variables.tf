variable "project_name" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "vpc_id" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "alb_security_group_id" { type = string }
variable "producer_target_group_arn" { type = string }
variable "grafana_target_group_arn" { type = string }

variable "kafka_bootstrap" { type = string }
variable "data_lake_bucket_name" { type = string }
variable "data_lake_bucket_arn" { type = string }
variable "alert_email" { type = string }

variable "owm_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "smtp_host" { type = string }

variable "smtp_user" {
  type      = string
  sensitive = true
}

variable "smtp_password" {
  type      = string
  sensitive = true
}

variable "smtp_user_secret_arn" {
  type    = string
  default = ""
}

variable "smtp_password_secret_arn" {
  type    = string
  default = ""
}

variable "smtp_from" {
  type    = string
  default = "alerts@airquality.local"
}

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

variable "rds_password" {
  type      = string
  sensitive = true
  default   = ""
}

variable "rds_password_secret_arn" {
  type    = string
  default = ""
}

variable "grafana_root_url" {
  type    = string
  default = ""
}