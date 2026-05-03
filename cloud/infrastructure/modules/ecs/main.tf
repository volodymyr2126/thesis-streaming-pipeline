data "aws_caller_identity" "current" {}

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecr_repository" "producer" {
  name                 = "${var.project_name}-producer"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = false }
}

resource "aws_ecr_repository" "alerting" {
  name                 = "${var.project_name}-alerting"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = false }
}

resource "aws_ecr_repository" "grafana" {
  name                 = "${var.project_name}-grafana"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = false }
}


resource "aws_iam_role" "execution" {
  name = "${var.project_name}-${var.environment}-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}


resource "aws_iam_role" "producer" {
  name = "${var.project_name}-${var.environment}-producer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "producer" {
  name = "s3-read"
  role = aws_iam_role.producer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [var.data_lake_bucket_arn, "${var.data_lake_bucket_arn}/*"]
    }]
  })
}

resource "aws_iam_role" "grafana" {
  name = "${var.project_name}-${var.environment}-grafana"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}


resource "aws_security_group" "tasks" {
  name_prefix = "${var.project_name}-${var.environment}-tasks-"
  vpc_id      = var.vpc_id
  description = "ECS tasks security group"

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [var.alb_security_group_id]
    description     = "Producer from ALB"
  }

  ingress {
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [var.alb_security_group_id]
    description     = "Grafana from ALB"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle { create_before_destroy = true }
}

resource "aws_cloudwatch_log_group" "producer" {
  name              = "/ecs/${var.project_name}-${var.environment}/producer"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "alerting" {
  name              = "/ecs/${var.project_name}-${var.environment}/alerting"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "grafana" {
  name              = "/ecs/${var.project_name}-${var.environment}/grafana"
  retention_in_days = 7
}

resource "aws_ecs_task_definition" "producer" {
  family                   = "${var.project_name}-${var.environment}-producer"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.producer.arn

  container_definitions = jsonencode([{
    name         = "producer"
    image        = "${aws_ecr_repository.producer.repository_url}:latest"
    portMappings = [{ containerPort = 8000 }]
    environment = [
      { name = "KAFKA_BOOTSTRAP_SERVERS", value = var.kafka_bootstrap },
      { name = "MINIO_BUCKET", value = var.data_lake_bucket_name },
      { name = "REPLAY_SPEED", value = "1000" },
      { name = "PRODUCER_MODE", value = "replay" },
      { name = "OWM_API_KEY", value = var.owm_api_key },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.producer.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "producer"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "alerting" {
  family                   = "${var.project_name}-${var.environment}-alerting"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn

  container_definitions = jsonencode([{
    name  = "alerting"
    image = "${aws_ecr_repository.alerting.repository_url}:latest"
    environment = [
      { name = "KAFKA_BOOTSTRAP_SERVERS", value = var.kafka_bootstrap },
      { name = "SMTP_HOST", value = var.smtp_host },
      { name = "SMTP_PORT", value = "587" },
      { name = "SMTP_USE_TLS", value = "true" },
      { name = "SMTP_FROM", value = var.smtp_from },
      { name = "ALERT_EMAIL_TO", value = var.alert_email },
      { name = "SMTP_USER", value = var.smtp_user },
      { name = "SMTP_PASSWORD", value = var.smtp_password },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.alerting.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "alerting"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "grafana" {
  family                   = "${var.project_name}-${var.environment}-grafana"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.grafana.arn

  container_definitions = jsonencode([{
    name         = "grafana"
    image        = "${aws_ecr_repository.grafana.repository_url}:latest"
    portMappings = [{ containerPort = 3000 }]
    environment = [
      { name = "GF_SECURITY_ADMIN_USER", value = "admin" },
      { name = "GF_SECURITY_ADMIN_PASSWORD", value = "admin" },
      { name = "GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH", value = "/etc/grafana/provisioning/dashboards/pipeline.json" },
      { name = "GF_AUTH_ANONYMOUS_ENABLED", value = "false" },
      { name = "GF_SERVER_ROOT_URL", value = var.grafana_root_url },
      { name = "POSTGRES_HOST", value = var.rds_host },
      { name = "POSTGRES_USER", value = var.rds_user },
      { name = "POSTGRES_DB", value = var.rds_db },
      { name = "POSTGRES_PASSWORD", value = var.rds_password },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.grafana.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "grafana"
      }
    }
  }])
}

resource "aws_ecs_service" "producer" {
  name            = "producer"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.producer.arn
  launch_type     = "FARGATE"
  desired_count   = 1

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = var.producer_target_group_arn
    container_name   = "producer"
    container_port   = 8000
  }

  lifecycle { ignore_changes = [task_definition] }
}

resource "aws_ecs_service" "alerting" {
  name            = "alerting"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.alerting.arn
  launch_type     = "FARGATE"
  desired_count   = 1

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  lifecycle { ignore_changes = [task_definition] }
}

resource "aws_ecs_service" "grafana" {
  name            = "grafana"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.grafana.arn
  launch_type     = "FARGATE"
  desired_count   = 1

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = var.grafana_target_group_arn
    container_name   = "grafana"
    container_port   = 3000
  }

  lifecycle { ignore_changes = [task_definition] }
}

# ── Flink (PyFlink local mode) ────────────────────────────────────────────────

resource "aws_ecr_repository" "flink" {
  name                 = "${var.project_name}-flink"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = false }
}

resource "aws_iam_role" "flink" {
  name = "${var.project_name}-${var.environment}-flink-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "flink" {
  name = "flink-permissions"
  role = aws_iam_role.flink.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [var.rds_password_secret_arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [var.data_lake_bucket_arn, "${var.data_lake_bucket_arn}/*"]
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "flink" {
  name              = "/ecs/${var.project_name}-${var.environment}/flink"
  retention_in_days = 7
}

resource "aws_ecs_task_definition" "flink" {
  family                   = "${var.project_name}-${var.environment}-flink"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 4096
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.flink.arn

  container_definitions = jsonencode([{
    name  = "flink"
    image = "${aws_ecr_repository.flink.repository_url}:latest"
    environment = [
      { name = "KAFKA_BOOTSTRAP", value = var.kafka_bootstrap },
      { name = "POSTGRES_HOST", value = var.rds_host },
      { name = "POSTGRES_PORT", value = "5432" },
      { name = "POSTGRES_DB", value = var.rds_db },
      { name = "POSTGRES_USER", value = var.rds_user },
      { name = "POSTGRES_PASSWORD_SECRET_ARN", value = var.rds_password_secret_arn },
      { name = "AWS_REGION", value = var.aws_region },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.flink.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "flink"
      }
    }
  }])
}

resource "aws_ecs_service" "flink" {
  name            = "flink"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.flink.arn
  launch_type     = "FARGATE"
  desired_count   = 1

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  lifecycle { ignore_changes = [task_definition] }
}