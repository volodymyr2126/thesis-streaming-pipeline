resource "aws_cloudwatch_log_group" "flink" {
  name              = "/aws/managed-flink/${var.project_name}-${var.environment}"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_stream" "flink" {
  name           = "flink-app"
  log_group_name = aws_cloudwatch_log_group.flink.name
}

resource "aws_iam_role" "flink" {
  name = "${var.project_name}-${var.environment}-flink"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "kinesisanalytics.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "flink" {
  name = "flink-permissions"
  role = aws_iam_role.flink.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      var.rds_password_secret_arn != "" ? [{
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [var.rds_password_secret_arn]
      }] : [],
      [{
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:ListBucket",
        ]
        Resource = [
          var.data_lake_bucket_arn,
          "${var.data_lake_bucket_arn}/*",
        ]
        },
        {
          Effect = "Allow"
          Action = [
            "kafka:DescribeCluster",
            "kafka:GetBootstrapBrokers",
            "kafka:ListScramSecrets",
          ]
          Resource = var.msk_cluster_arn
        },
        {
          Effect = "Allow"
          Action = [
            "ec2:DescribeVpcs",
            "ec2:DescribeSubnets",
            "ec2:DescribeSecurityGroups",
            "ec2:DescribeDhcpOptions",
            "ec2:CreateNetworkInterface",
            "ec2:CreateNetworkInterfacePermission",
            "ec2:DescribeNetworkInterfaces",
            "ec2:DeleteNetworkInterface",
          ]
          Resource = "*"
        },
        {
          Effect = "Allow"
          Action = [
            "logs:CreateLogGroup",
            "logs:CreateLogStream",
            "logs:PutLogEvents",
            "logs:DescribeLogGroups",
            "logs:DescribeLogStreams",
          ]
          Resource = "${aws_cloudwatch_log_group.flink.arn}:*"
        },
        {
          Effect   = "Allow"
          Action   = ["cloudwatch:PutMetricData"]
          Resource = "*"
        },
      ]
    )
  })
}

resource "aws_kinesisanalyticsv2_application" "main" {
  name                   = "${var.project_name}-${var.environment}-flink"
  runtime_environment    = "FLINK-1_18"
  service_execution_role = aws_iam_role.flink.arn

  application_configuration {
    application_code_configuration {
      code_content {
        s3_content_location {
          bucket_arn = var.data_lake_bucket_arn
          file_key   = "flink-app/application.zip"
        }
      }
      code_content_type = "ZIPFILE"
    }

    flink_application_configuration {
      checkpoint_configuration {
        configuration_type            = "CUSTOM"
        checkpointing_enabled         = true
        checkpoint_interval           = 60000
        min_pause_between_checkpoints = 5000
      }

      monitoring_configuration {
        configuration_type = "CUSTOM"
        log_level          = "INFO"
        metrics_level      = "APPLICATION"
      }

      parallelism_configuration {
        configuration_type   = "CUSTOM"
        auto_scaling_enabled = false
        parallelism          = 1
        parallelism_per_kpu  = 1
      }
    }

    environment_properties {
      property_group {
        property_group_id = "kinesis.analytics.flink.run.options"
        property_map = {
          python  = "stream_processor.py"
          jarfile = "lib/flink-sql-connector-kafka-3.0.2-1.18.jar"
        }
      }

      property_group {
        property_group_id = "FlinkApplicationProperties"
        property_map = { for k, v in {
          KAFKA_BOOTSTRAP              = var.kafka_bootstrap
          AWS_REGION                   = var.aws_region
          POSTGRES_HOST                = var.rds_host
          POSTGRES_PORT                = "5432"
          POSTGRES_DB                  = var.rds_db
          POSTGRES_USER                = var.rds_user
          POSTGRES_PASSWORD_SECRET_ARN = var.rds_password_secret_arn
          BASELINES_FILE               = "s3://${var.data_lake_bucket_name}/baselines/baselines.json"
        } : k => v if v != "" }
      }
    }

    vpc_configuration {
      security_group_ids = [var.vpc_internal_sg_id]
      subnet_ids         = var.private_subnet_ids
    }
  }

  cloudwatch_logging_options {
    log_stream_arn = aws_cloudwatch_log_stream.flink.arn
  }
}