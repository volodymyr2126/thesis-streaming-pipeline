resource "aws_sesv2_email_identity" "alert" {
  email_identity = var.alert_email
}

resource "aws_iam_user" "ses_smtp" {
  name = "${var.project_name}-${var.environment}-ses-smtp"
}

resource "aws_iam_user_policy" "ses_smtp" {
  name = "ses-send"
  user = aws_iam_user.ses_smtp.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ses:SendRawEmail"]
      Resource = "*"
    }]
  })
}

resource "aws_iam_access_key" "ses_smtp" {
  user = aws_iam_user.ses_smtp.name
}

resource "aws_secretsmanager_secret" "ses_smtp_user" {
  name                    = "${var.project_name}/${var.environment}/ses-smtp-user"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "ses_smtp_user" {
  secret_id     = aws_secretsmanager_secret.ses_smtp_user.id
  secret_string = aws_iam_access_key.ses_smtp.id
}

resource "aws_secretsmanager_secret" "ses_smtp_password" {
  name                    = "${var.project_name}/${var.environment}/ses-smtp-password"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "ses_smtp_password" {
  secret_id = aws_secretsmanager_secret.ses_smtp_password.id
  # The SES SMTP password is derived from the IAM secret access key.
  # After apply, compute it with:
  #   python3 -c "
  #     import hmac, hashlib, base64
  #     key = b'AWS4' + b'<IAM_SECRET_KEY>'
  #     for msg in [b'us-east-1', b'ses', b'aws4_request', b'SendRawEmail']:
  #         key = hmac.new(key, msg, hashlib.sha256).digest()
  #     print(base64.b64encode(b'\x04' + key).decode())
  #   "
  # Then update this secret value with the computed password.
  secret_string = aws_iam_access_key.ses_smtp.secret
}