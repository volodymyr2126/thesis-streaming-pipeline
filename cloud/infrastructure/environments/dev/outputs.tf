output "msk_bootstrap_brokers" {
  value = module.msk.bootstrap_brokers
}

output "data_lake_bucket_name" {
  value = local.data_lake_bucket
}

output "ses_smtp_host" {
  value = module.ses.smtp_host
}
