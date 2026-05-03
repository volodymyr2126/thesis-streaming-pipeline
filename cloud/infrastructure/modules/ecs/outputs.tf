output "cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "producer_ecr_url" {
  value = aws_ecr_repository.producer.repository_url
}

output "alerting_ecr_url" {
  value = aws_ecr_repository.alerting.repository_url
}

output "grafana_ecr_url" {
  value = aws_ecr_repository.grafana.repository_url
}

output "flink_ecr_url" {
  value = aws_ecr_repository.flink.repository_url
}