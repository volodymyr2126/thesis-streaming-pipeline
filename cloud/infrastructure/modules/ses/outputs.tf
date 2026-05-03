output "smtp_host" {
  value = "email-smtp.${var.aws_region}.amazonaws.com"
}

output "smtp_user_secret_arn" {
  value = aws_secretsmanager_secret.ses_smtp_user.arn
}

output "smtp_password_secret_arn" {
  value = aws_secretsmanager_secret.ses_smtp_password.arn
}

output "iam_access_key_id" {
  value     = aws_iam_access_key.ses_smtp.id
  sensitive = true
}

output "iam_secret_access_key" {
  value     = aws_iam_access_key.ses_smtp.secret
  sensitive = true
}