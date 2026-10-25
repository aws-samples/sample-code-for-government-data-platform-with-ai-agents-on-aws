# AgentCore shared: the runtimes' security group, vended log permissions and Transaction Search for the account

# The geospatial runtime: outbound HTTPS to anywhere, for the public STAC catalogue and the satellite imagery
resource "aws_security_group" "agentcore" {
  #checkov:skip=CKV2_AWS_5:Attached to the geospatial runtime through module.agentcore_geospatial.security_group_ids, which the graph check doesn't follow
  #checkov:skip=CKV_AWS_382:The geospatial agent reads the public Earth Search STAC catalogue and imagery through the NAT gateway (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html)
  name        = "${var.PrefixCode}-sg-agentcore"
  description = "AgentCore runtimes: HTTPS egress only"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "HTTPS to AWS APIs and public data"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name         = "${var.PrefixCode}-sg-agentcore"
    resourcetype = "network"
    codeblock    = "79-agentcore-shared"
  }
}

# The data and walkthrough runtimes: HTTPS to the VPC endpoints only, no route to the internet
resource "aws_security_group" "agentcore_aws_only" {
  #checkov:skip=CKV2_AWS_5:Attached to the data and walkthrough runtimes through module.agentcore_*.security_group_ids, which the graph check doesn't follow
  name        = "${var.PrefixCode}-sg-agentcore-aws-only"
  description = "AgentCore data and walkthrough runtimes: HTTPS to VPC endpoints only"
  vpc_id      = aws_vpc.main.id

  egress {
    description     = "HTTPS to the interface endpoints"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.vpce.id]
  }

  egress {
    description     = "HTTPS to the S3 and DynamoDB gateway endpoints"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [aws_vpc_endpoint.s3.prefix_list_id, aws_vpc_endpoint.dynamodb.prefix_list_id]
  }

  tags = {
    Name         = "${var.PrefixCode}-sg-agentcore-aws-only"
    resourcetype = "network"
    codeblock    = "79-agentcore-shared"
  }
}

# Lets vended log delivery write to every runtime's vended group; scoped by pattern so the modules can depend on it
resource "aws_cloudwatch_log_resource_policy" "vended_logs_delivery" {
  policy_name = "${var.PrefixCode}-vended-logs-delivery"

  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "VendedLogsDelivery"
      Effect    = "Allow"
      Principal = { Service = "delivery.logs.amazonaws.com" }
      Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource  = "arn:aws:logs:${var.Region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/vendedlogs/bedrock-agentcore/*:*"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })
}

# No TRACES delivery: every runtime's traces reach X-Ray through the ADOT exporter in the container

# CloudWatch Transaction Search: X-Ray stores traces in aws/spans, which feeds the /admin session viewer. A Region-wide setting that stays on after a destroy
resource "aws_xray_trace_segment_destination" "transaction_search" {
  destination = "CloudWatchLogs"

  # Nothing in the destination references the policy, but the API rejects the change until the policy exists
  depends_on = [aws_cloudwatch_log_resource_policy.xray_transaction_search]
}

# Lets X-Ray write spans to CloudWatch Logs
resource "aws_cloudwatch_log_resource_policy" "xray_transaction_search" {
  policy_name = "${var.PrefixCode}-xray-transaction-search"

  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "TransactionSearchXRayAccess"
      Effect    = "Allow"
      Principal = { Service = "xray.amazonaws.com" }
      Action    = ["logs:PutLogEvents", "logs:CreateLogStream"]
      Resource = [
        "arn:aws:logs:${var.Region}:${data.aws_caller_identity.current.account_id}:log-group:aws/spans:*",
        "arn:aws:logs:${var.Region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/application-signals/data:*"
      ]
      Condition = {
        ArnLike      = { "aws:SourceArn" = "arn:aws:xray:${var.Region}:${data.aws_caller_identity.current.account_id}:*" }
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })
}
