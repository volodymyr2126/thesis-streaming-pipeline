variable "project_name" { type = string }
variable "environment" { type = string }

variable "memory_store_hours" {
  type    = number
  default = 24
}

variable "magnetic_store_days" {
  type    = number
  default = 365
}
