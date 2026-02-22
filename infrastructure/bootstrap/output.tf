output "state_bucket_name" {
  description = "S3 bucket name for Terraform state"
  value       = aws_s3_bucket.terraform_state.id
}

output "lock_table_name" {
  description = "DynamoDB table name for state locking"
  value       = aws_dynamodb_table.terraform_lock.name
}
# lock_table_name = "thesis-pipeline-tflock"
# state_bucket_name = "thesis-pipeline-tfstate-767397977983"