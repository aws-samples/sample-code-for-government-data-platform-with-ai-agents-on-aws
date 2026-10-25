# Secrets Manager: the data source API keys (entered by hand, never in git) and the webapp cookie signing key

resource "aws_secretsmanager_secret" "api_keys_public" {
  #checkov:skip=CKV2_AWS_57:Third-party API keys issued by external providers, no programmatic rotation
  name                    = "${var.PrefixCode}-api-keys-public"
  description             = "API keys for free/open government data sources (e.g. DWP Stat-Xplore)"
  kms_key_id              = aws_kms_key.datalake.arn
  recovery_window_in_days = 0 # Lets a destroy and redeploy reuse the name; the keys must be re-entered after a destroy

  tags = {
    Name         = "${var.PrefixCode}-api-keys-public"
    resourcetype = "security"
    codeblock    = "12-secrets"
  }
}

resource "aws_secretsmanager_secret_version" "api_keys_public" {
  secret_id = aws_secretsmanager_secret.api_keys_public.id
  secret_string = jsonencode({
    dwp_stat_xplore = "REPLACE_ME"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "webapp_cookie_secret" {
  #checkov:skip=CKV2_AWS_57:Cookie signing key is static, rotation would invalidate every active session
  name                    = "${var.PrefixCode}-webapp-cookie-secret"
  description             = "HMAC signing key for webapp session cookies"
  kms_key_id              = aws_kms_key.datalake.arn
  recovery_window_in_days = 0

  tags = {
    Name         = "${var.PrefixCode}-webapp-cookie-secret"
    resourcetype = "security"
    codeblock    = "12-secrets"
  }
}

resource "aws_secretsmanager_secret_version" "webapp_cookie_secret" {
  secret_id     = aws_secretsmanager_secret.webapp_cookie_secret.id
  secret_string = random_password.cookie_secret.result
}

resource "random_password" "cookie_secret" {
  length  = 64
  special = false
}
