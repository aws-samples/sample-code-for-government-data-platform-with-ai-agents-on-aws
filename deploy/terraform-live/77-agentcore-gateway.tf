# AgentCore Gateway: the platform's data tools as MCP endpoints for external clients

# IAM role for the gateway to invoke Lambda functions
resource "aws_iam_role" "agentcore_gateway" {
  name = "${var.PrefixCode}-iamrole-agentcore-gateway"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "bedrock-agentcore.amazonaws.com" }
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })

  tags = {
    Name         = "${var.PrefixCode}-iamrole-agentcore-gateway"
    resourcetype = "security"
    codeblock    = "77-agentcore-gateway"
  }
}

resource "aws_iam_role_policy" "agentcore_gateway_invoke" {
  name = "${var.PrefixCode}-policy-agentcore-gateway-invoke"
  role = aws_iam_role.agentcore_gateway.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "lambda:InvokeFunction"
      Resource = [
        module.gw_query_data.function_arn,
        module.gw_describe_schema.function_arn,
        module.gw_summarise_area.function_arn,
        module.gw_list_datasets.function_arn,
      ]
    }]
  })
}

# AWS_IAM auth: any same-account principal allowed InvokeGateway can call it
resource "aws_bedrockagentcore_gateway" "main" {
  name     = "${var.PrefixCode}-mcp-gateway"
  role_arn = aws_iam_role.agentcore_gateway.arn

  authorizer_type = "AWS_IAM"
  protocol_type   = "MCP"

  protocol_configuration {
    mcp {
      instructions = "Government Data Platform: UK government datasets at local authority level covering crime, schools, housing, population, wellbeing, employment, earnings, and more for England and Wales."
    }
  }

  description = "MCP Gateway for UK Government Open Data Platform"

  tags = {
    Name         = "${var.PrefixCode}-mcp-gateway"
    resourcetype = "compute"
    codeblock    = "77-agentcore-gateway"
  }
}

# Shared Redshift IAM statements reused across all data-querying gateway Lambdas
locals {
  gw_redshift_iam = [
    {
      # The Data API has no resource-level permissions (https://docs.aws.amazon.com/redshift/latest/mgmt/data-api-iam.html)
      Effect   = "Allow"
      Action   = ["redshift-data:ExecuteStatement", "redshift-data:DescribeStatement", "redshift-data:GetStatementResult", "redshift-data:CancelStatement"]
      Resource = "*"
    },
    {
      Effect   = "Allow"
      Action   = ["redshift-serverless:GetCredentials"]
      Resource = aws_redshiftserverless_workgroup.main.arn
    },
  ]
  gw_redshift_env = {
    REDSHIFT_WORKGROUP = aws_redshiftserverless_workgroup.main.workgroup_name
    REDSHIFT_DATABASE  = aws_redshiftserverless_namespace.main.db_name
  }
  # The data source registry, read for the attribution statements each tool result carries
  gw_registry_iam = [{
    Effect   = "Allow"
    Action   = ["dynamodb:Scan"]
    Resource = aws_dynamodb_table.data_source_registry.arn
  }]
  gw_registry_env = {
    DATA_SOURCE_REGISTRY_TABLE = aws_dynamodb_table.data_source_registry.name
  }
}
# The tool Lambdas run in the private subnets: Redshift Data API and DynamoDB through the VPC endpoints, no route to the internet
resource "aws_security_group" "gateway_tools" {
  name        = "${var.PrefixCode}-sg-gateway-tools"
  description = "Gateway tool Lambdas: HTTPS egress only"
  vpc_id      = aws_vpc.main.id
  egress {
    description     = "HTTPS to the interface endpoints"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.vpce.id]
  }
  egress {
    description     = "HTTPS to the DynamoDB gateway endpoint"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [aws_vpc_endpoint.dynamodb.prefix_list_id]
  }
  tags = {
    Name         = "${var.PrefixCode}-sg-gateway-tools"
    resourcetype = "network"
    codeblock    = "77-agentcore-gateway"
  }
}

# Lambda: execute SQL against Redshift (SELECT only, 500 row cap)
module "gw_query_data" {
  source                 = "./modules/lambda_function"
  prefix_code            = var.PrefixCode
  name                   = "gw-query-data"
  source_dir             = "${path.module}/../lambda/gw-query-data"
  timeout                = 120
  codeblock              = "77-agentcore-gateway"
  kms_key_arn            = aws_kms_key.datalake.arn
  layers                 = [aws_lambda_layer_version.common.arn]
  vpc_subnet_ids         = aws_subnet.private[*].id
  vpc_security_group_ids = [aws_security_group.gateway_tools.id]

  environment_variables = merge(local.gw_redshift_env, local.gw_registry_env, {
    DATASET_TRACKING_TABLE = aws_dynamodb_table.dataset_tracking.name
  })

  additional_iam_statements = concat(local.gw_redshift_iam, local.gw_registry_iam, [{
    Effect   = "Allow"
    Action   = ["dynamodb:BatchWriteItem"]
    Resource = aws_dynamodb_table.dataset_tracking.arn
  }])
}

# Lambda: describe tables and columns from the gold schema
module "gw_describe_schema" {
  source                 = "./modules/lambda_function"
  prefix_code            = var.PrefixCode
  name                   = "gw-describe-schema"
  source_dir             = "${path.module}/../lambda/gw-describe-schema"
  timeout                = 120
  codeblock              = "77-agentcore-gateway"
  kms_key_arn            = aws_kms_key.datalake.arn
  layers                 = [aws_lambda_layer_version.common.arn]
  vpc_subnet_ids         = aws_subnet.private[*].id
  vpc_security_group_ids = [aws_security_group.gateway_tools.id]

  environment_variables     = local.gw_redshift_env
  additional_iam_statements = local.gw_redshift_iam
}

# Lambda: area profile with national averages, timeseries, HPI, crime hotspots and schools (6 sequential queries)
module "gw_summarise_area" {
  source                 = "./modules/lambda_function"
  prefix_code            = var.PrefixCode
  name                   = "gw-summarise-area"
  source_dir             = "${path.module}/../lambda/gw-summarise-area"
  timeout                = 300
  codeblock              = "77-agentcore-gateway"
  kms_key_arn            = aws_kms_key.datalake.arn
  layers                 = [aws_lambda_layer_version.common.arn]
  vpc_subnet_ids         = aws_subnet.private[*].id
  vpc_security_group_ids = [aws_security_group.gateway_tools.id]

  environment_variables = merge(local.gw_redshift_env, local.gw_registry_env, {
    DATASET_TRACKING_TABLE = aws_dynamodb_table.dataset_tracking.name
  })
  additional_iam_statements = concat(local.gw_redshift_iam, local.gw_registry_iam, [{
    Effect   = "Allow"
    Action   = ["dynamodb:BatchWriteItem"]
    Resource = aws_dynamodb_table.dataset_tracking.arn
  }])
}

# Lambda: list all data sources from the DynamoDB registry
module "gw_list_datasets" {
  source                 = "./modules/lambda_function"
  prefix_code            = var.PrefixCode
  name                   = "gw-list-datasets"
  source_dir             = "${path.module}/../lambda/gw-list-datasets"
  timeout                = 30
  codeblock              = "77-agentcore-gateway"
  kms_key_arn            = aws_kms_key.datalake.arn
  layers                 = [aws_lambda_layer_version.common.arn]
  vpc_subnet_ids         = aws_subnet.private[*].id
  vpc_security_group_ids = [aws_security_group.gateway_tools.id]

  environment_variables     = local.gw_registry_env
  additional_iam_statements = local.gw_registry_iam
}

# One gateway target per MCP tool
resource "aws_bedrockagentcore_gateway_target" "query_data" {
  name               = "query-data"
  gateway_identifier = aws_bedrockagentcore_gateway.main.gateway_id
  description        = "Execute SQL against UK government datasets for England and Wales."

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = module.gw_query_data.function_arn
        tool_schema {
          inline_payload {
            name        = "query_data"
            description = "Execute SQL against UK government datasets at local authority level. Returns columns, rows, row_count and the attribution statements to show with the data. Capped at 500 rows."
            input_schema {
              type        = "object"
              description = "SQL query parameters"
              property {
                name        = "sql"
                type        = "string"
                description = "A SELECT or WITH SQL query against the Redshift data warehouse."
                required    = true
              }
            }
          }
        }
      }
    }
  }
}

resource "aws_bedrockagentcore_gateway_target" "describe_schema" {
  name               = "describe-schema"
  gateway_identifier = aws_bedrockagentcore_gateway.main.gateway_id
  description        = "List available tables and columns in the government data warehouse."

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = module.gw_describe_schema.function_arn
        tool_schema {
          inline_payload {
            name        = "describe_schema"
            description = "List tables and columns. Call with no args for full schema, or pass table_name for one table."
            input_schema {
              type        = "object"
              description = "Schema query parameters"
              property {
                name        = "table_name"
                type        = "string"
                description = "Optional table name to filter to (e.g. rs_fact_earnings)."
              }
            }
          }
        }
      }
    }
  }
}

resource "aws_bedrockagentcore_gateway_target" "summarise_area" {
  name               = "summarise-area"
  gateway_identifier = aws_bedrockagentcore_gateway.main.gateway_id
  description        = "Get a comprehensive profile of any local authority in England and Wales."

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = module.gw_summarise_area.function_arn
        tool_schema {
          inline_payload {
            name        = "summarise_area"
            description = "Get area profile with population, wellbeing, education, housing, crime, deprivation and employment."
            input_schema {
              type        = "object"
              description = "Area query parameters"
              property {
                name        = "area_name"
                type        = "string"
                description = "Name of the local authority (e.g. Lewisham, Manchester, Hartlepool)"
                required    = true
              }
            }
          }
        }
      }
    }
  }
}

resource "aws_bedrockagentcore_gateway_target" "list_datasets" {
  name               = "list-datasets"
  gateway_identifier = aws_bedrockagentcore_gateway.main.gateway_id
  description        = "List all available government data sources with date ranges and update frequencies."

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = module.gw_list_datasets.function_arn
        tool_schema {
          inline_payload {
            name        = "list_datasets"
            description = "List all government data sources with date ranges, update frequencies, gold table names and the attribution statement each is owed."
            input_schema {
              type        = "object"
              description = "No parameters required"
            }
          }
        }
      }
    }
  }
}

output "mcp_gateway_url" {
  value       = aws_bedrockagentcore_gateway.main.gateway_url
  description = "MCP endpoint for the AgentCore Gateway. Callers sign requests with SigV4 (service bedrock-agentcore)."
}
