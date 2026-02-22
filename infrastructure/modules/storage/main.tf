
data "aws_caller_identity" "current" {}

     resource "aws_s3_bucket" "data_lake" {
       bucket = "${var.project_name}-data-lake-${data.aws_caller_identity.current
     .account_id}"

       tags = {
         Project     = var.project_name
         Environment = var.environment
         Purpose     = "data-lake"
       }
     }

     resource "aws_s3_bucket_versioning" "data_lake" {
       bucket = aws_s3_bucket.data_lake.id

       versioning_configuration {
         status = "Enabled"
       }
     }

     resource "aws_s3_bucket_server_side_encryption_configuration" "data_lake" {
       bucket = aws_s3_bucket.data_lake.id

       rule {
         apply_server_side_encryption_by_default {
           sse_algorithm = "AES256"
         }
       }
     }

     resource "aws_s3_bucket_public_access_block" "data_lake" {
       bucket = aws_s3_bucket.data_lake.id

       block_public_acls       = true
       block_public_policy     = true
       ignore_public_acls      = true
       restrict_public_buckets = true
     }

     resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
       bucket = aws_s3_bucket.data_lake.id

       rule {
         id     = "transition-to-cheaper-storage"
         status = "Enabled"
         filter {}
         transition {
           days          = 90
           storage_class = "STANDARD_IA"
         }

         transition {
           days          = 180
           storage_class = "GLACIER"
         }

         abort_incomplete_multipart_upload {
           days_after_initiation = 7
         }
       }
     }
