# All data source ingestion Lambdas, Step Functions, and schedules

# Shared by the ingest and gateway Lambdas: HTTP fetch with retries, bronze writes, the NOMIS, ONS and Stat-Xplore clients, the registry and the Redshift Data API runner
data "archive_file" "common_layer" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/layers/common"
  output_path = "${path.module}/../lambda/layers/common.zip"
}

# Every ingest Lambda writes under bronze/; GetObject covers the HeadObject that skips rewriting an unchanged file
locals {
  bronze_put = {
    Effect   = "Allow"
    Action   = ["s3:PutObject", "s3:GetObject"]
    Resource = "${module.datalake.bucket_arn}/bronze/*"
  }
}

resource "aws_lambda_layer_version" "common" {
  layer_name               = "${var.PrefixCode}-layer-common"
  filename                 = data.archive_file.common_layer.output_path
  source_code_hash         = data.archive_file.common_layer.output_base64sha256
  compatible_runtimes      = ["python3.14"]
  compatible_architectures = ["arm64"]
}

# Police API (crime data)

# Lists the police force ids and the months to fetch
module "get_police_forces" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "get-police-forces"
  source_dir  = "${path.module}/../lambda/get-police-forces"
  timeout     = 30
  memory_size = 128
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    MONTHS_TO_FETCH = "12"
  }
}

# Pulls one force's crime data to bronze
module "ingest_police_api" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-police-api"
  source_dir  = "${path.module}/../lambda/ingest-police-api"
  timeout     = 900
  memory_size = 512
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

# One execution per force, ten at a time
resource "aws_sfn_state_machine" "police_ingestion" {
  name     = "${var.PrefixCode}-sfn-police-ingestion"
  role_arn = aws_iam_role.sfn_police_ingestion.arn

  depends_on = [aws_iam_role_policy.sfn_police_ingestion]

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_logs.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  tracing_configuration {
    enabled = true
  }

  definition = jsonencode({
    Comment = "Ingest crime data from all 44 UK police forces"
    StartAt = "GetForces"
    States = {
      GetForces = {
        Type       = "Task"
        Resource   = module.get_police_forces.function_arn
        Next       = "ProcessAllForces"
        ResultPath = "$.forcesResult"
      }
      ProcessAllForces = {
        Type           = "Map"
        ItemsPath      = "$.forcesResult.tasks"
        MaxConcurrency = 10
        ItemSelector = {
          "force.$" = "$$.Map.Item.Value.force"
          "date.$"  = "$$.Map.Item.Value.date"
        }
        ItemProcessor = {
          ProcessorConfig = { Mode = "INLINE" }
          StartAt         = "IngestForce"
          States = {
            IngestForce = {
              Type     = "Task"
              Resource = module.ingest_police_api.function_arn
              End      = true
              Retry = [{
                ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException"]
                IntervalSeconds = 5
                MaxAttempts     = 3
                BackoffRate     = 2
              }]
              Catch = [{
                ErrorEquals = ["States.ALL"]
                ResultPath  = "$.error"
                Next        = "HandleError"
              }]
            }
            HandleError = {
              Type   = "Pass"
              Result = { status = "failed" }
              End    = true
            }
          }
        }
        ResultPath = "$.results"
        Next       = "Done"
      }
      Done = { Type = "Succeed" }
    }
  })

  tags = {
    Name         = "${var.PrefixCode}-sfn-police-ingestion"
    resourcetype = "compute"
    codeblock    = "21-ingest-lambdas"
  }
}

resource "aws_iam_role" "sfn_police_ingestion" {
  name = "${var.PrefixCode}-iamrole-sfn-police-ingestion"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.PrefixCode}-iamrole-sfn-police-ingestion"
    resourcetype = "security"
    codeblock    = "21-ingest-lambdas"
  }
}

resource "aws_iam_role_policy" "sfn_police_ingestion" {
  #checkov:skip=CKV_AWS_355:Step Functions log delivery and X-Ray actions have no resource-level permissions (https://docs.aws.amazon.com/step-functions/latest/dg/cw-logs.html)
  name = "${var.PrefixCode}-policy-sfn-police-ingestion"
  role = aws_iam_role.sfn_police_ingestion.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(local.sfn_base_statements, [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [module.get_police_forces.function_arn, module.ingest_police_api.function_arn]
      }
    ])
  })
}

# Shared scheduler role for EventBridge to invoke Step Functions and Lambdas
resource "aws_iam_role" "eventbridge_scheduler" {
  name = "${var.PrefixCode}-iamrole-eventbridge-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.PrefixCode}-iamrole-eventbridge-scheduler"
    resourcetype = "security"
    codeblock    = "21-ingest-lambdas"
  }
}

# One schedule per scheduled source in local.ingest_sources (20-ingest-orchestrator.tf), invoking its Lambda or state machine
resource "aws_scheduler_schedule" "ingest" {
  for_each = local.ingest_schedules

  name        = "${var.PrefixCode}-schedule-ingest-${each.key}"
  group_name  = "default"
  kms_key_arn = aws_kms_key.datalake.arn

  flexible_time_window { mode = "OFF" }
  schedule_expression = each.value.schedule

  target {
    arn      = each.value.arn
    role_arn = aws_iam_role.eventbridge_scheduler.arn
    input    = "{}"
  }
}

# Every scheduled target, in one policy per target type
resource "aws_iam_role_policy" "scheduler_lambdas" {
  name = "${var.PrefixCode}-policy-scheduler-lambdas"
  role = aws_iam_role.eventbridge_scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = [for s in values(local.ingest_schedules) : s.arn if s.type == "lambda"]
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_state_machines" {
  name = "${var.PrefixCode}-policy-scheduler-state-machines"
  role = aws_iam_role.eventbridge_scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["states:StartExecution"]
      Resource = concat([for s in values(local.ingest_schedules) : s.arn if s.type == "step-function"], [aws_sfn_state_machine.etl_to_gold.arn])
    }]
  })
}

# Schedules set kms_key_arn; the execution role must decrypt the payload itself
resource "aws_iam_role_policy" "eventbridge_scheduler_kms" {
  name = "${var.PrefixCode}-policy-scheduler-kms"
  role = aws_iam_role.eventbridge_scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["kms:Decrypt"]
      Resource = aws_kms_key.datalake.arn
    }]
  })
}

# ONS data sources

module "ingest_ons_earnings" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-ons-earnings"
  source_dir  = "${path.module}/../lambda/ingest-ons-earnings"
  timeout     = 900
  memory_size = 1024
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
    {
      # Files from earlier runs are deleted once the edition files are written
      Effect   = "Allow"
      Action   = ["s3:DeleteObject"]
      Resource = "${module.datalake.bucket_arn}/bronze/ons/earnings/*"
    },
    {
      Effect   = "Allow"
      Action   = ["s3:ListBucket"]
      Resource = module.datalake.bucket_arn
    },
  ]
}

module "ingest_ons_employment" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-ons-employment"
  source_dir  = "${path.module}/../lambda/ingest-ons-employment"
  timeout     = 600
  memory_size = 1024
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

module "ingest_geography_reference" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-geography-reference"
  source_dir  = "${path.module}/../lambda/ingest-geography-reference"
  timeout     = 900
  memory_size = 512
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

module "ingest_ons_gva" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-ons-gva"
  source_dir  = "${path.module}/../lambda/ingest-ons-gva"
  timeout     = 600
  memory_size = 512
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
    {
      # Versioned files from earlier runs are deleted once the fixed-name file is written
      Effect   = "Allow"
      Action   = ["s3:DeleteObject"]
      Resource = "${module.datalake.bucket_arn}/bronze/ons/gva/*"
    },
    {
      Effect   = "Allow"
      Action   = ["s3:ListBucket"]
      Resource = module.datalake.bucket_arn
    },
  ]
}

module "ingest_ons_population" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-ons-population"
  source_dir  = "${path.module}/../lambda/ingest-ons-population"
  timeout     = 600
  memory_size = 512
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

module "ingest_ons_wellbeing" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-ons-wellbeing"
  source_dir  = "${path.module}/../lambda/ingest-ons-wellbeing"
  timeout     = 120
  memory_size = 256
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
    {
      # Versioned files from earlier runs are deleted once the fixed-name file is written
      Effect   = "Allow"
      Action   = ["s3:DeleteObject"]
      Resource = "${module.datalake.bucket_arn}/bronze/ons/wellbeing/*"
    },
    {
      Effect   = "Allow"
      Action   = ["s3:ListBucket"]
      Resource = module.datalake.bucket_arn
    },
  ]
}

module "ingest_ons_hpi" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-ons-hpi"
  source_dir  = "${path.module}/../lambda/ingest-ons-hpi"
  timeout     = 120
  memory_size = 256
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

# Land Registry (price paid data), one execution per year

module "get_land_registry_years" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "get-land-registry-years"
  source_dir  = "${path.module}/../lambda/get-land-registry-years"
  timeout     = 30
  memory_size = 128
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    {
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "${module.datalake.bucket_arn}/bronze/*"
    },
    {
      Effect   = "Allow"
      Action   = ["s3:ListBucket"]
      Resource = module.datalake.bucket_arn
    },
  ]
}

module "ingest_land_registry" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-land-registry"
  source_dir  = "${path.module}/../lambda/ingest-land-registry"
  timeout     = 900
  memory_size = 512
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

resource "aws_sfn_state_machine" "land_registry_ingestion" {
  name     = "${var.PrefixCode}-sfn-land-registry-ingestion"
  role_arn = aws_iam_role.sfn_land_registry.arn

  depends_on = [aws_iam_role_policy.sfn_land_registry]

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_logs.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  tracing_configuration {
    enabled = true
  }

  definition = jsonencode({
    Comment = "Download Land Registry Price Paid data for all years (1995–current)"
    StartAt = "GetYears"
    States = {
      GetYears = {
        Type       = "Task"
        Resource   = module.get_land_registry_years.function_arn
        Next       = "DownloadAllYears"
        ResultPath = "$.yearsResult"
      }
      DownloadAllYears = {
        Type           = "Map"
        ItemsPath      = "$.yearsResult.tasks"
        MaxConcurrency = 5
        ItemProcessor = {
          ProcessorConfig = { Mode = "INLINE" }
          StartAt         = "DownloadYear"
          States = {
            DownloadYear = {
              Type     = "Task"
              Resource = module.ingest_land_registry.function_arn
              End      = true
              Retry = [{
                ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException"]
                IntervalSeconds = 10
                MaxAttempts     = 3
                BackoffRate     = 2
              }]
              Catch = [{
                ErrorEquals = ["States.ALL"]
                ResultPath  = "$.error"
                Next        = "HandleError"
              }]
            }
            HandleError = {
              Type   = "Pass"
              Result = { status = "failed" }
              End    = true
            }
          }
        }
        ResultPath = "$.results"
        Next       = "Done"
      }
      Done = { Type = "Succeed" }
    }
  })

  tags = {
    Name         = "${var.PrefixCode}-sfn-land-registry-ingestion"
    resourcetype = "compute"
    codeblock    = "21-ingest-lambdas"
  }
}

resource "aws_iam_role" "sfn_land_registry" {
  name = "${var.PrefixCode}-iamrole-sfn-land-registry"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.PrefixCode}-iamrole-sfn-land-registry"
    resourcetype = "security"
    codeblock    = "21-ingest-lambdas"
  }
}

resource "aws_iam_role_policy" "sfn_land_registry" {
  #checkov:skip=CKV_AWS_355:Step Functions log delivery and X-Ray actions have no resource-level permissions (https://docs.aws.amazon.com/step-functions/latest/dg/cw-logs.html)
  name = "${var.PrefixCode}-policy-sfn-land-registry"
  role = aws_iam_role.sfn_land_registry.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(local.sfn_base_statements, [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [module.get_land_registry_years.function_arn, module.ingest_land_registry.function_arn]
      }
    ])
  })
}

# DfE (school performance + school detail)

module "ingest_dfe_school_performance" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-dfe-school-perf"
  source_dir  = "${path.module}/../lambda/ingest-dfe-school-performance"
  timeout     = 300
  memory_size = 512
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

module "ingest_dfe_school_detail" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-dfe-school-detail"
  source_dir  = "${path.module}/../lambda/ingest-dfe-school-detail"
  timeout     = 300
  memory_size = 512
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

# NOMIS (claimant count + APS)

module "ingest_nomis_claimant_count" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-nomis-claimant-count"
  source_dir  = "${path.module}/../lambda/ingest-nomis-claimant-count"
  timeout     = 120
  memory_size = 256
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

module "ingest_nomis_aps" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-nomis-aps"
  source_dir  = "${path.module}/../lambda/ingest-nomis-aps"
  timeout     = 900
  memory_size = 1024
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

# DfT Road Traffic

module "ingest_dft_road_traffic" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-dft-road-traffic"
  source_dir  = "${path.module}/../lambda/ingest-dft-road-traffic"
  timeout     = 300
  memory_size = 256
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

# MHCLG Deprivation (IMD 2025)

module "ingest_mhclg_deprivation" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-mhclg-deprivation"
  source_dir  = "${path.module}/../lambda/ingest-mhclg-deprivation"
  timeout     = 120
  memory_size = 256
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

# DWP Universal Credit

module "ingest_dwp_universal_credit" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-dwp-universal-credit"
  source_dir  = "${path.module}/../lambda/ingest-dwp-universal-credit"
  timeout     = 600 # One 300 s Stat-Xplore table query plus the LA valueset pages
  memory_size = 512
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET    = module.datalake.bucket_id
    API_KEYS_SECRET_ID = aws_secretsmanager_secret.api_keys_public.id
  }

  additional_iam_statements = [
    local.bronze_put,
    {
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = aws_secretsmanager_secret.api_keys_public.arn
    }
  ]
}

# HMRC Trade (regional trade statistics)

module "ingest_hmrc_trade" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-hmrc-trade"
  source_dir  = "${path.module}/../lambda/ingest-hmrc-trade"
  timeout     = 900
  memory_size = 1024
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
    {
      # Pages are staged, copied into rts/ once every year succeeded, then the staging and stale pages are deleted
      Effect   = "Allow"
      Action   = ["s3:DeleteObject"]
      Resource = "${module.datalake.bucket_arn}/bronze/hmrc/trade/rts/*"
    },
    {
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:DeleteObject"]
      Resource = "${module.datalake.bucket_arn}/bronze/hmrc/trade/rts-staging/*"
    },
    {
      Effect   = "Allow"
      Action   = ["s3:ListBucket"]
      Resource = module.datalake.bucket_arn
    },
  ]
}

# NHS RTT (waiting times)

module "ingest_nhs_rtt" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-nhs-rtt"
  source_dir  = "${path.module}/../lambda/ingest-nhs-rtt"
  timeout     = 900
  memory_size = 512
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

# NHS ODS (GP practices, pharmacies, trusts)

module "ingest_nhs_ods" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-nhs-ods"
  source_dir  = "${path.module}/../lambda/ingest-nhs-ods"
  timeout     = 900
  memory_size = 256
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

# DEFRA Air Quality (PM2.5)

module "ingest_defra_air_quality" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-defra-air-quality"
  source_dir  = "${path.module}/../lambda/ingest-defra-air-quality"
  timeout     = 120
  memory_size = 256
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

# MHCLG Spending (revenue outturn)

module "ingest_mhclg_spending" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-mhclg-spending"
  source_dir  = "${path.module}/../lambda/ingest-mhclg-spending"
  timeout     = 120
  memory_size = 256
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

# Jobs Density (NOMIS)

module "ingest_jobs_density" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-jobs-density"
  source_dir  = "${path.module}/../lambda/ingest-jobs-density"
  timeout     = 120
  memory_size = 256
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

# Business Counts (NOMIS)

module "ingest_business_counts" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-business-counts"
  source_dir  = "${path.module}/../lambda/ingest-business-counts"
  timeout     = 120
  memory_size = 256
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

# ONS Births & Deaths

module "ingest_ons_births_deaths" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-ons-births-deaths"
  source_dir  = "${path.module}/../lambda/ingest-ons-births-deaths"
  timeout     = 120
  memory_size = 256
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET = module.datalake.bucket_id
  }

  additional_iam_statements = [
    local.bronze_put,
  ]
}

# DWP Housing Benefit

module "ingest_dwp_housing_benefit" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-dwp-housing-benefit"
  source_dir  = "${path.module}/../lambda/ingest-dwp-housing-benefit"
  timeout     = 600 # One 300 s Stat-Xplore table query plus the LA valueset pages
  memory_size = 512
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET    = module.datalake.bucket_id
    API_KEYS_SECRET_ID = aws_secretsmanager_secret.api_keys_public.id
  }

  additional_iam_statements = [
    local.bronze_put,
    {
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = aws_secretsmanager_secret.api_keys_public.arn
    }
  ]
}

# DWP Children in Low Income Families (CiLIF)

module "ingest_dwp_cilif" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-dwp-cilif"
  source_dir  = "${path.module}/../lambda/ingest-dwp-cilif"
  timeout     = 900 # Three 300 s Stat-Xplore table queries, one per measure
  memory_size = 512
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET    = module.datalake.bucket_id
    API_KEYS_SECRET_ID = aws_secretsmanager_secret.api_keys_public.id
  }

  additional_iam_statements = [
    local.bronze_put,
    {
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = aws_secretsmanager_secret.api_keys_public.arn
    }
  ]
}

# DWP Personal Independence Payment (PIP)

module "ingest_dwp_pip" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-dwp-pip"
  source_dir  = "${path.module}/../lambda/ingest-dwp-pip"
  timeout     = 900
  memory_size = 512
  codeblock   = "21-ingest-lambdas"
  kms_key_arn = aws_kms_key.datalake.arn
  layers      = [aws_lambda_layer_version.common.arn]

  environment_variables = {
    DATALAKE_BUCKET    = module.datalake.bucket_id
    API_KEYS_SECRET_ID = aws_secretsmanager_secret.api_keys_public.id
  }

  additional_iam_statements = [
    local.bronze_put,
    {
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = aws_secretsmanager_secret.api_keys_public.arn
    }
  ]
}

