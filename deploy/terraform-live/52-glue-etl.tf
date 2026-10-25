# Glue ETL: the bronze-to-silver jobs and the silver-to-gold dimensional model

locals {
  # One entry per bronze-to-silver job: the script suffix (deploy/glue/bronze-to-silver-<key>.py) and its worker count
  bronze_to_silver_jobs = {
    "police-crime"             = 2
    "ons-wellbeing"            = 2
    "ons-population"           = 2
    "land-registry-price-paid" = 2
    "dfe-school-performance"   = 2
    "ons-earnings"             = 2
    "ons-geography"            = 2
    "dfe-school-detail"        = 2
    "nomis-claimant-count"     = 2
    "ons-employment"           = 2
    "mhclg-deprivation"        = 2
    "dwp-universal-credit"     = 2
    "nomis-aps"                = 2
    "ons-gva"                  = 4
    "hmrc-trade"               = 4
    "dft-road-traffic"         = 2
    "ons-hpi"                  = 2
    "nhs-rtt"                  = 2
    "nhs-ods"                  = 2
    "defra-air-quality"        = 2
    "mhclg-spending"           = 2
    "jobs-density"             = 2
    "business-counts"          = 2
    "ons-births-deaths"        = 2
    "dwp-housing-benefit"      = 2
    "dwp-cilif"                = 2
    "dwp-pip"                  = 2
  }
}

# Pre-created: the first ETL in a new account starts every job at once and they race to create these groups
resource "aws_cloudwatch_log_group" "glue_jobs" {
  for_each          = toset(["output", "error"])
  name              = "/aws-glue/jobs/${aws_glue_security_configuration.etl.name}-role/${aws_iam_role.glue_etl.name}/${each.key}"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.datalake.arn

  tags = {
    Name         = "${var.PrefixCode}-logs-glue-${each.key}"
    resourcetype = "monitoring"
    codeblock    = "52-glue-etl"
  }
}

# S3 script uploads

# Shared setup and write helpers, loaded by every job through --extra-py-files
resource "aws_s3_object" "glue_lib_common" {
  bucket      = module.datalake.bucket_id
  key         = "glue-scripts/lib/glue_common.py"
  source      = "${path.module}/../glue/lib/glue_common.py"
  source_hash = filemd5("${path.module}/../glue/lib/glue_common.py")

  tags = {
    Name         = "${var.PrefixCode}-glue-lib-common"
    resourcetype = "analytics"
    codeblock    = "52-glue-etl"
  }
}

# The gold job's table specs and build functions
resource "aws_s3_object" "glue_lib_gold" {
  for_each    = toset(["gold_tables", "gold_build"])
  bucket      = module.datalake.bucket_id
  key         = "glue-scripts/lib/${each.key}.py"
  source      = "${path.module}/../glue/lib/${each.key}.py"
  source_hash = filemd5("${path.module}/../glue/lib/${each.key}.py")

  tags = {
    Name         = "${var.PrefixCode}-glue-lib-${replace(each.key, "_", "-")}"
    resourcetype = "analytics"
    codeblock    = "52-glue-etl"
  }
}

resource "aws_s3_object" "glue_script_bronze_to_silver" {
  for_each    = local.bronze_to_silver_jobs
  bucket      = module.datalake.bucket_id
  key         = "glue-scripts/bronze-to-silver-${each.key}.py"
  source      = "${path.module}/../glue/bronze-to-silver-${each.key}.py"
  source_hash = filemd5("${path.module}/../glue/bronze-to-silver-${each.key}.py")

  tags = {
    Name         = "${var.PrefixCode}-glue-script-bronze-to-silver-${each.key}"
    resourcetype = "analytics"
    codeblock    = "52-glue-etl"
  }
}

resource "aws_s3_object" "glue_script_silver_to_gold" {
  bucket      = module.datalake.bucket_id
  key         = "glue-scripts/silver-to-gold-dimensional-model.py"
  source      = "${path.module}/../glue/silver-to-gold-dimensional-model.py"
  source_hash = filemd5("${path.module}/../glue/silver-to-gold-dimensional-model.py")

  tags = {
    Name         = "${var.PrefixCode}-glue-script-silver-to-gold"
    resourcetype = "analytics"
    codeblock    = "52-glue-etl"
  }
}

# IAM Role for Glue jobs

resource "aws_iam_role" "glue_etl" {
  name = "${var.PrefixCode}-iamrole-glue-etl"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.PrefixCode}-iamrole-glue-etl"
    resourcetype = "security"
    codeblock    = "52-glue-etl"
  }
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_etl.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_etl" {
  name = "${var.PrefixCode}-policy-glue-etl"
  role = aws_iam_role.glue_etl.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          module.datalake.bucket_arn,
          "${module.datalake.bucket_arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey"
        ]
        Resource = aws_kms_key.datalake.arn
      },
      {
        Sid    = "S3TablesAccess"
        Effect = "Allow"
        Action = [
          "s3tables:GetTable",
          "s3tables:GetTableBucket",
          "s3tables:GetTableData",
          "s3tables:PutTableData",
          "s3tables:GetTableMetadataLocation",
          "s3tables:UpdateTableMetadataLocation",
          "s3tables:CreateTable",
          "s3tables:ListTables",
          "s3tables:GetNamespace",
          "s3tables:ListNamespaces"
        ]
        Resource = [
          aws_s3tables_table_bucket.gold.arn,
          "${aws_s3tables_table_bucket.gold.arn}/*",
          aws_s3tables_table_bucket.silver.arn,
          "${aws_s3tables_table_bucket.silver.arn}/*"
        ]
      },
      {
        # The security configuration encrypts job logs with KMS; AWSGlueServiceRole grants the other log actions but not this one
        Effect   = "Allow"
        Action   = ["logs:AssociateKmsKey"]
        Resource = "arn:aws:logs:${var.Region}:${data.aws_caller_identity.current.account_id}:log-group:/aws-glue/*"
      },
      {
        Sid    = "DataSourceRegistry"
        Effect = "Allow"
        Action = [
          "dynamodb:UpdateItem"
        ]
        Resource = aws_dynamodb_table.data_source_registry.arn
      }
    ]
  })
}

# Security configuration

resource "aws_glue_security_configuration" "etl" {
  name = "${var.PrefixCode}-glue-security"

  encryption_configuration {
    cloudwatch_encryption {
      cloudwatch_encryption_mode = "SSE-KMS"
      kms_key_arn                = aws_kms_key.datalake.arn
    }

    job_bookmarks_encryption {
      job_bookmarks_encryption_mode = "CSE-KMS"
      kms_key_arn                   = aws_kms_key.datalake.arn
    }

    s3_encryption {
      s3_encryption_mode = "SSE-KMS"
      kms_key_arn        = aws_kms_key.datalake.arn
    }
  }
}

# Shared Glue job defaults

locals {
  glue_default_args = {
    "--job-language"                = "python"
    "--DATALAKE_BUCKET"             = module.datalake.bucket_id
    "--DATABASE_NAME"               = aws_s3tables_namespace.silver.namespace
    "--S3_TABLE_BUCKET_NAME_SILVER" = aws_s3tables_table_bucket.silver.name
    "--datalake-formats"            = "iceberg"
    "--conf"                        = "spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions"
    "--enable-metrics"              = "true"
    "--enable-spark-ui"             = "true"
    "--spark-event-logs-path"       = "s3://${module.datalake.bucket_id}/glue-spark-logs/"
    "--enable-auto-scaling"         = "true"
    "--job-bookmark-option"         = "job-bookmark-disable"
    "--enable-job-insights"         = "true"
    "--extra-py-files"              = "s3://${module.datalake.bucket_id}/${aws_s3_object.glue_lib_common.key}"
  }
}

# Glue Jobs

# The ETL Step Function finds these by the ${var.PrefixCode}-glue-bronze-to-silver- name prefix
resource "aws_glue_job" "bronze_to_silver" {
  for_each = local.bronze_to_silver_jobs
  name     = "${var.PrefixCode}-glue-bronze-to-silver-${each.key}"
  role_arn = aws_iam_role.glue_etl.arn

  command {
    name            = "glueetl"
    script_location = "s3://${module.datalake.bucket_id}/${aws_s3_object.glue_script_bronze_to_silver[each.key].key}"
    python_version  = "3"
  }

  default_arguments      = local.glue_default_args
  glue_version           = "5.0"
  worker_type            = "G.1X"
  number_of_workers      = each.value
  timeout                = 30
  max_retries            = 0
  security_configuration = aws_glue_security_configuration.etl.name

  tags = {
    Name         = "${var.PrefixCode}-glue-bronze-to-silver-${each.key}"
    resourcetype = "analytics"
    codeblock    = "52-glue-etl"
  }
}

resource "aws_glue_job" "silver_to_gold" {
  name     = "${var.PrefixCode}-glue-silver-to-gold-dimensional-model"
  role_arn = aws_iam_role.glue_etl.arn

  command {
    name            = "glueetl"
    script_location = "s3://${module.datalake.bucket_id}/${aws_s3_object.glue_script_silver_to_gold.key}"
    python_version  = "3"
  }

  default_arguments = merge(local.glue_default_args, {
    "--SILVER_DATABASE"           = aws_s3tables_namespace.silver.namespace
    "--GOLD_DATABASE"             = aws_s3tables_namespace.gold.namespace
    "--REGISTRY_TABLE"            = aws_dynamodb_table.data_source_registry.name
    "--INGEST_SCHEDULES"          = jsonencode({ for s in values(local.ingest_schedules) : s.source_id => s.schedule })
    "--S3_TABLE_BUCKET_NAME"      = aws_s3tables_table_bucket.gold.name
    "--additional-python-modules" = "shapely==2.2.0"
    "--extra-py-files" = join(",", concat(
      [local.glue_default_args["--extra-py-files"]],
      [for o in aws_s3_object.glue_lib_gold : "s3://${module.datalake.bucket_id}/${o.key}"],
    ))
  })

  glue_version           = "5.0"
  worker_type            = "G.1X"
  number_of_workers      = 4
  timeout                = 30
  max_retries            = 0
  security_configuration = aws_glue_security_configuration.etl.name

  tags = {
    Name         = "${var.PrefixCode}-glue-silver-to-gold-dimensional-model"
    resourcetype = "analytics"
    codeblock    = "52-glue-etl"
  }
}
