resource "aws_security_group" "msk" {
  name_prefix = "${var.project_name}-${var.environment}-msk-"
  vpc_id      = var.vpc_id
  description = "MSK cluster security group"

  ingress {
    from_port   = 9092
    to_port     = 9092
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    description = "Kafka PLAINTEXT from VPC"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-${var.environment}-msk" }

  lifecycle { create_before_destroy = true }
}

resource "aws_cloudwatch_log_group" "msk" {
  name              = "/aws/msk/${var.project_name}-${var.environment}"
  retention_in_days = 7
}

resource "aws_msk_configuration" "main" {
  name           = "${var.project_name}-${var.environment}-config"
  kafka_versions = ["3.6.0"]

  server_properties = <<-EOF
    auto.create.topics.enable=true
    delete.topic.enable=true
    log.retention.hours=24
    num.partitions=3
    default.replication.factor=2
    min.insync.replicas=1
  EOF
}

resource "aws_msk_cluster" "main" {
  cluster_name           = "${var.project_name}-${var.environment}"
  kafka_version          = "3.6.0"
  number_of_broker_nodes = 2

  broker_node_group_info {
    instance_type  = "kafka.t3.small"
    client_subnets = var.private_subnet_ids
    storage_info {
      ebs_storage_info { volume_size = 20 }
    }
    security_groups = [aws_security_group.msk.id]
  }

  encryption_info {
    encryption_in_transit {
      client_broker = "PLAINTEXT"
      in_cluster    = false
    }
  }

  configuration_info {
    arn      = aws_msk_configuration.main.arn
    revision = aws_msk_configuration.main.latest_revision
  }

  open_monitoring {
    prometheus {
      jmx_exporter { enabled_in_broker = false }
      node_exporter { enabled_in_broker = false }
    }
  }

  logging_info {
    broker_logs {
      cloudwatch_logs {
        enabled   = true
        log_group = aws_cloudwatch_log_group.msk.name
      }
    }
  }

  tags = { Name = "${var.project_name}-${var.environment}-msk" }
}