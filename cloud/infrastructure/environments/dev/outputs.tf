output "alb_url" {
  description = "ALB DNS — open in browser for Grafana dashboard"
  value       = "http://${module.alb.alb_dns_name}"
}

output "producer_url" {
  value = "http://${module.alb.alb_dns_name}:80  (routed by path to producer on :8000)"
}

output "msk_bootstrap_brokers" {
  value = module.msk.bootstrap_brokers
}

output "ecr_flink" {
  value = module.ecs.flink_ecr_url
}

output "ecr_producer" {
  value = module.ecs.producer_ecr_url
}

output "ecr_alerting" {
  value = module.ecs.alerting_ecr_url
}

output "ecr_grafana" {
  value = module.ecs.grafana_ecr_url
}

output "data_lake_bucket_name" {
  value = local.data_lake_bucket
}