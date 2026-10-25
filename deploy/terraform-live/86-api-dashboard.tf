# Dashboard API: GET /metrics for the dashboard container, IAM-signed

# Dashboard live state: one item per agent, written by the webapp
resource "aws_dynamodb_table" "dashboard_live" {
  name         = "${var.PrefixCode}-dashboard-live"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.datalake.arn
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name         = "${var.PrefixCode}-dynamodb-dashboard-live"
    resourcetype = "database"
    codeblock    = "86-api-dashboard"
  }
}

# Lambda function
module "gw_dashboard_metrics" {
  source      = "./modules/lambda_function"
  prefix_code = var.PrefixCode
  name        = "gw-dashboard-metrics"
  source_dir  = "${path.module}/../lambda/gw-dashboard-metrics"
  timeout     = 30
  codeblock   = "86-api-dashboard"
  kms_key_arn = aws_kms_key.datalake.arn

  environment_variables = {
    DATASET_TRACKING_TABLE     = aws_dynamodb_table.dataset_tracking.name
    DATA_SOURCE_REGISTRY_TABLE = aws_dynamodb_table.data_source_registry.name
    DASHBOARD_LIVE_TABLE       = aws_dynamodb_table.dashboard_live.name
    SHARED_ANSWERS_TABLE       = aws_dynamodb_table.shared_answers.name
  }

  additional_iam_statements = [
    {
      Effect   = "Allow"
      Action   = ["dynamodb:Scan", "dynamodb:Query"]
      Resource = aws_dynamodb_table.dataset_tracking.arn
    },
    {
      Effect   = "Allow"
      Action   = ["dynamodb:Scan"]
      Resource = aws_dynamodb_table.data_source_registry.arn
    },
    {
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem"]
      Resource = aws_dynamodb_table.dashboard_live.arn
    },
    {
      Effect   = "Allow"
      Action   = ["dynamodb:Scan"]
      Resource = aws_dynamodb_table.shared_answers.arn
    },
  ]
}

# HTTP API
resource "aws_apigatewayv2_api" "dashboard" {
  name          = "${var.PrefixCode}-api-dashboard"
  protocol_type = "HTTP"

  tags = {
    Name         = "${var.PrefixCode}-api-dashboard"
    resourcetype = "compute"
    codeblock    = "86-api-dashboard"
  }
}

# Integration + route
resource "aws_apigatewayv2_integration" "dashboard_metrics" {
  api_id                 = aws_apigatewayv2_api.dashboard.id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.gw_dashboard_metrics.function_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

# Only the dashboard container reads this; it signs the request with its task role (SigV4)
resource "aws_apigatewayv2_route" "dashboard_metrics" {
  api_id             = aws_apigatewayv2_api.dashboard.id
  route_key          = "GET /metrics"
  target             = "integrations/${aws_apigatewayv2_integration.dashboard_metrics.id}"
  authorization_type = "AWS_IAM"
}

resource "aws_lambda_permission" "dashboard_metrics" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = module.gw_dashboard_metrics.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.dashboard.execution_arn}/*/GET/metrics"
}

# Auto-deploy stage
resource "aws_apigatewayv2_stage" "dashboard" {
  api_id      = aws_apigatewayv2_api.dashboard.id
  name        = "$default"
  auto_deploy = true

  # One dashboard container polling every 15 s; anything beyond this is abuse
  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.dashboard_api.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      responseLength = "$context.responseLength"
    })
  }

  tags = {
    Name         = "${var.PrefixCode}-api-dashboard-stage"
    resourcetype = "compute"
    codeblock    = "86-api-dashboard"
  }
}

resource "aws_cloudwatch_log_group" "dashboard_api" {
  name              = "/aws/apigateway/${var.PrefixCode}-api-dashboard"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.datalake.arn

  tags = {
    Name         = "${var.PrefixCode}-logs-api-dashboard"
    resourcetype = "monitoring"
    codeblock    = "86-api-dashboard"
  }
}
