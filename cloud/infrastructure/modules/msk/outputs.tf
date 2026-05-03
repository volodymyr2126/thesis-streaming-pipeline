output "bootstrap_brokers" {
  description = "PLAINTEXT bootstrap broker string"
  value       = aws_msk_cluster.main.bootstrap_brokers
}

output "cluster_arn" {
  value = aws_msk_cluster.main.arn
}

output "security_group_id" {
  value = aws_security_group.msk.id
}