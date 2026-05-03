output "alb_dns_name" {
  value = aws_lb.main.dns_name
}

output "alb_security_group_id" {
  value = aws_security_group.alb.id
}

output "producer_target_group_arn" {
  value = aws_lb_target_group.producer.arn
}

output "grafana_target_group_arn" {
  value = aws_lb_target_group.grafana.arn
}