output "data_lake_bucket" {
  description = "Name of the data lake S3 bucket for raw data storage"
  value       = aws_s3_bucket.data_lake.id
}

output "log_group_name" {
  description = "CloudWatch log group name for pipeline monitoring"
  value       = aws_cloudwatch_log_group.pipeline_logs.name
}

output "aws_account_id" {
  description = "AWS Account ID where resources are created"
  value       = data.aws_caller_identity.current.account_id
}

output "aws_region" {
  description = "AWS region where resources are created"
  value       = var.aws_region
}