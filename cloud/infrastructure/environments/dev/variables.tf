variable "aws_region" {
  type    = string
  default = "eu-central-1"
}

variable "project_name" {
  type    = string
  default = "thesis-pipeline"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "alert_email" {
  type = string
}

variable "owm_api_key" {
  type      = string
  sensitive = true
  default   = ""
}