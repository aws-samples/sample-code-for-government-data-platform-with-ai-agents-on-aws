# Redshift Serverless data warehouse; Spectrum reads the gold S3 Tables through a Glue resource link

# Admin password stored in Secrets Manager (used by Query Editor v2)
resource "aws_secretsmanager_secret" "redshift_admin" {
  #checkov:skip=CKV2_AWS_57:No rotation; the password is only used by Query Editor v2 and the setup Lambda
  name                    = "${var.PrefixCode}-redshift-admin"
  description             = "Redshift Serverless admin credentials"
  kms_key_id              = aws_kms_key.datalake.arn
  recovery_window_in_days = 0 # Allow immediate recreation on destroy/apply cycles

  tags = {
    Name         = "${var.PrefixCode}-redshift-admin"
    resourcetype = "security"
    codeblock    = "61-redshift"
    # Tag key must start with "Redshift" for secret to appear in Query Editor v2 dropdown
    "Redshift" = "true"
  }
}

resource "random_password" "redshift_admin" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret_version" "redshift_admin" {
  secret_id = aws_secretsmanager_secret.redshift_admin.id
  secret_string = jsonencode({
    username = "admin"
    password = random_password.redshift_admin.result
  })
}

# Allow VPC services to connect on port 5439
resource "aws_security_group" "redshift" {
  #checkov:skip=CKV2_AWS_5:SG is attached to aws_redshiftserverless_workgroup.main
  #checkov:skip=CKV_AWS_382:Spectrum needs egress to S3 and Glue (https://docs.aws.amazon.com/redshift/latest/mgmt/rs-security-group-public-private.html)
  name        = "${var.PrefixCode}-sg-redshift"
  description = "Redshift Serverless security group"
  vpc_id      = aws_vpc.main.id

  # Inbound from the VPC
  ingress {
    description = "Allow VPC CIDR on port 5439"
    from_port   = 5439
    to_port     = 5439
    protocol    = "tcp"
    cidr_blocks = [local.vpc_cidr]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name         = "${var.PrefixCode}-sg-redshift"
    resourcetype = "security"
    codeblock    = "61-redshift"
  }
}


# Pre-created with retention, otherwise log_exports creates them with Never Expire
resource "aws_cloudwatch_log_group" "redshift_logs" {
  for_each          = toset(["userlog", "connectionlog", "useractivitylog"])
  name              = "/aws/redshift/${var.PrefixCode}-namespace/${each.value}"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.datalake.arn

  tags = {
    Name         = "${var.PrefixCode}-redshift-${each.value}"
    resourcetype = "monitoring"
    codeblock    = "61-redshift"
  }
}

# Namespace holds the analytics database, encrypted with our KMS key
resource "aws_redshiftserverless_namespace" "main" {
  namespace_name      = "${var.PrefixCode}-namespace"
  admin_username      = jsondecode(aws_secretsmanager_secret_version.redshift_admin.secret_string)["username"]
  admin_user_password = jsondecode(aws_secretsmanager_secret_version.redshift_admin.secret_string)["password"]
  db_name             = "analytics"
  kms_key_id          = aws_kms_key.datalake.arn

  iam_roles = [aws_iam_role.redshift_spectrum.arn]

  log_exports = ["userlog", "connectionlog", "useractivitylog"]

  tags = {
    Name         = "${var.PrefixCode}-namespace"
    resourcetype = "analytics"
    codeblock    = "61-redshift"
  }

  # log_exports creates the groups itself if they don't exist yet; nothing in the namespace references them
  depends_on = [aws_cloudwatch_log_group.redshift_logs]
}

# Workgroup in the private subnets
resource "aws_redshiftserverless_workgroup" "main" {
  namespace_name = aws_redshiftserverless_namespace.main.namespace_name
  workgroup_name = "${var.PrefixCode}-workgroup"
  base_capacity  = 8
  max_capacity   = 32

  security_group_ids = [aws_security_group.redshift.id]
  subnet_ids         = aws_subnet.private[*].id

  publicly_accessible = false

  # Backstop for a query a caller stopped waiting for without cancelling; the Lambdas and agents cancel at their own deadlines
  config_parameter {
    parameter_key   = "max_query_execution_time"
    parameter_value = "900"
  }

  config_parameter {
    parameter_key   = "enable_case_sensitive_identifier"
    parameter_value = "true"
  }

  tags = {
    Name         = "${var.PrefixCode}-workgroup"
    resourcetype = "analytics"
    codeblock    = "61-redshift"
  }

  # The service adds its own default parameters alongside ours, which would otherwise show as drift on every plan
  lifecycle {
    ignore_changes = [config_parameter]
  }
}

# Spectrum role, read-only on the gold tables
resource "aws_iam_role" "redshift_spectrum" {
  name = "${var.PrefixCode}-iamrole-redshift-spectrum"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "redshift.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.PrefixCode}-iamrole-redshift-spectrum"
    resourcetype = "security"
    codeblock    = "61-redshift"
  }
}

resource "aws_iam_role_policy" "redshift_spectrum" {
  name = "${var.PrefixCode}-policy-redshift-spectrum"
  role = aws_iam_role.redshift_spectrum.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3ReadAccess"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          module.datalake.bucket_arn,
          "${module.datalake.bucket_arn}/*"
        ]
      },
      {
        Sid    = "S3TablesAccess"
        Effect = "Allow"
        Action = [
          "s3tables:GetTable",
          "s3tables:GetTableBucket",
          "s3tables:GetTableData",
          "s3tables:GetTableMetadataLocation",
          "s3tables:ListTables",
          "s3tables:GetNamespace",
          "s3tables:ListNamespaces"
        ]
        Resource = [
          aws_s3tables_table_bucket.gold.arn,
          "${aws_s3tables_table_bucket.gold.arn}/*"
        ]
      },
      {
        Sid    = "GlueCatalogAccess"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetTable",
          "glue:GetTables",
          "glue:GetPartition",
          "glue:GetPartitions",
          "glue:BatchGetPartition",
          "glue:GetCatalog"
        ]
        Resource = [
          "arn:aws:glue:${var.Region}:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:${var.Region}:${data.aws_caller_identity.current.account_id}:catalog/s3tablescatalog",
          "arn:aws:glue:${var.Region}:${data.aws_caller_identity.current.account_id}:catalog/s3tablescatalog/*",
          "arn:aws:glue:${var.Region}:${data.aws_caller_identity.current.account_id}:database/${aws_glue_catalog_database.gold_s3tables_link.name}",
          "arn:aws:glue:${var.Region}:${data.aws_caller_identity.current.account_id}:database/s3tablescatalog/*/*",
          "arn:aws:glue:${var.Region}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.gold_s3tables_link.name}/*",
          "arn:aws:glue:${var.Region}:${data.aws_caller_identity.current.account_id}:table/s3tablescatalog/*/*/*"
        ]
      },
      {
        Sid    = "KMSDecrypt"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = aws_kms_key.datalake.arn
      }
    ]
  })
}


# Usage cap that logs rather than blocks
resource "aws_redshiftserverless_usage_limit" "monthly" {
  resource_arn  = aws_redshiftserverless_workgroup.main.arn
  usage_type    = "serverless-compute"
  amount        = 200
  period        = "monthly"
  breach_action = "log"
}


# Runs on apply: creates Spectrum external schema + views + grants
module "redshift_setup" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "redshift-setup"
  source_dir  = "${path.module}/../lambda/redshift-setup"
  timeout     = 900 # A full refresh runs about 70 statements serially against a cold workgroup
  codeblock   = "61-redshift"
  kms_key_arn = aws_kms_key.datalake.arn

  environment_variables = {
    WORKGROUP_NAME      = aws_redshiftserverless_workgroup.main.workgroup_name
    DATABASE_NAME       = aws_redshiftserverless_namespace.main.db_name
    GOLD_DATABASE       = aws_glue_catalog_database.gold_s3tables_link.name
    SPECTRUM_ROLE_ARN   = aws_iam_role.redshift_spectrum.arn
    REDSHIFT_SECRET_ARN = aws_secretsmanager_secret.redshift_admin.arn
  }

  additional_iam_statements = [
    {
      Effect = "Allow"
      Action = [
        "redshift-data:ExecuteStatement",
        "redshift-data:BatchExecuteStatement",
        "redshift-data:DescribeStatement",
        "redshift-data:GetStatementResult",
        "redshift-data:CancelStatement"
      ]
      Resource = "*"
    },
    {
      Effect = "Allow"
      Action = [
        "redshift-serverless:GetCredentials"
      ]
      Resource = aws_redshiftserverless_workgroup.main.arn
    },
    {
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue"
      ]
      Resource = aws_secretsmanager_secret.redshift_admin.arn
    }
  ]
}

# Runs gold once on first deploy to create the external schema; the ETL Step Function applies later SQL changes after ingestion
resource "aws_lambda_invocation" "redshift_setup" {
  function_name = module.redshift_setup.function_name

  input = jsonencode({
    action  = "gold"
    trigger = "terraform"
  })
}


# SELECT 1 every 4 minutes in business hours (08:00 to 18:00 UTC, Mon to Fri) to stop Serverless scaling to zero
resource "aws_scheduler_schedule" "redshift_warmup" {
  count       = var.RedshiftWarmupEnabled ? 1 : 0
  name        = "${var.PrefixCode}-schedule-redshift-warmup"
  group_name  = "default"
  kms_key_arn = aws_kms_key.datalake.arn

  flexible_time_window { mode = "OFF" }
  schedule_expression = "cron(0/4 8-17 ? * MON-FRI *)"

  target {
    arn      = module.redshift_setup.function_arn
    role_arn = aws_iam_role.eventbridge_scheduler.arn
    input    = jsonencode({ action = "warmup" })
  }
}

resource "aws_iam_role_policy" "scheduler_redshift_warmup" {
  count = var.RedshiftWarmupEnabled ? 1 : 0
  name  = "${var.PrefixCode}-policy-scheduler-redshift-warmup"
  role  = aws_iam_role.eventbridge_scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = module.redshift_setup.function_arn
    }]
  })
}
