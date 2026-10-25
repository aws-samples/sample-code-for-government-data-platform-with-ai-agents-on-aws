# Cognito user pool the webapp signs users in against

# Cognito User Pool (Essentials tier, password sign-in, users created by an administrator only)

resource "aws_cognito_user_pool" "webapp" {
  name = "${var.PrefixCode}-cognito-webapp"

  user_pool_tier           = "ESSENTIALS"
  auto_verified_attributes = ["email"]
  username_attributes      = ["email"]
  deletion_protection      = "INACTIVE" # Users are created by hand after deploy and are recreated after a teardown

  sign_in_policy {
    allowed_first_auth_factors = ["PASSWORD"]
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true

    string_attribute_constraints {
      min_length = 0
      max_length = 2048
    }
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  tags = {
    Name         = "${var.PrefixCode}-cognito-webapp"
    resourcetype = "security"
    codeblock    = "84-cognito-auth"
  }
}

# Cognito Domain

resource "aws_cognito_user_pool_domain" "webapp" {
  domain                = "${var.PrefixCode}-auth-${data.aws_caller_identity.current.account_id}"
  user_pool_id          = aws_cognito_user_pool.webapp.id
  managed_login_version = 2
}

# Cognito App Client

resource "aws_cognito_user_pool_client" "webapp" {
  name         = "${var.PrefixCode}-cognito-client-webapp"
  user_pool_id = aws_cognito_user_pool.webapp.id

  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email"]
  supported_identity_providers         = ["COGNITO"]
  explicit_auth_flows                  = ["ALLOW_USER_AUTH", "ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  callback_urls = [
    "https://${aws_cloudfront_distribution.webapp.domain_name}/auth/callback"
  ]

  logout_urls = [
    "https://${aws_cloudfront_distribution.webapp.domain_name}"
  ]

  # Short-lived tokens
  id_token_validity      = 1
  access_token_validity  = 10
  refresh_token_validity = 10

  token_validity_units {
    id_token      = "hours"
    access_token  = "minutes"
    refresh_token = "hours"
  }
}

# Managed Login Branding (GOV.UK colours)

resource "aws_cognito_managed_login_branding" "webapp" {
  user_pool_id = aws_cognito_user_pool.webapp.id
  client_id    = aws_cognito_user_pool_client.webapp.id
  settings     = file("${path.module}/../cognito-branding/settings.json")

  # Cognito normalises the settings document on save; edits to settings.json need a taint to redeploy
  lifecycle {
    ignore_changes = [settings, use_cognito_provided_values]
  }
}

# Cognito config read by the webapp and the smoke test; SecureString because it holds the client secret

resource "aws_ssm_parameter" "cognito_config" {
  name   = "/${var.PrefixCode}/cognito/config"
  type   = "SecureString"
  key_id = aws_kms_key.datalake.arn

  value = jsonencode({
    region        = var.Region
    user_pool_id  = aws_cognito_user_pool.webapp.id
    client_id     = aws_cognito_user_pool_client.webapp.id
    client_secret = aws_cognito_user_pool_client.webapp.client_secret
    domain        = "${aws_cognito_user_pool_domain.webapp.domain}.auth.${var.Region}.amazoncognito.com"
  })

  tags = {
    Name         = "${var.PrefixCode}-ssm-cognito-config"
    resourcetype = "security"
    codeblock    = "84-cognito-auth"
  }
}

# Cognito region, user pool id and client id, read by the dashboard to check sign-in tokens
resource "aws_ssm_parameter" "cognito_verify" {
  name   = "/${var.PrefixCode}/cognito-verify"
  type   = "SecureString"
  key_id = aws_kms_key.datalake.arn

  value = jsonencode({
    region       = var.Region
    user_pool_id = aws_cognito_user_pool.webapp.id
    client_id    = aws_cognito_user_pool_client.webapp.id
  })

  tags = {
    Name         = "${var.PrefixCode}-ssm-cognito-verify"
    resourcetype = "security"
    codeblock    = "84-cognito-auth"
  }
}

# Smoke test user. No stored password: the pipeline's Test stage sets a random one on each run
resource "aws_cognito_user" "ci_test" {
  user_pool_id   = aws_cognito_user_pool.webapp.id
  username       = "ci-test@example.com"
  message_action = "SUPPRESS"

  attributes = {
    email          = "ci-test@example.com"
    email_verified = "true"
  }
}
