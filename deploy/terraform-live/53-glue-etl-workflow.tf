# Step Function running the ETL: detect bronze changes, then for the changed sources the bronze-to-silver jobs, silver-to-gold, Redshift refresh

# Lambda: detect-bronze-changes

module "detect_bronze_changes" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "detect-bronze-changes"
  source_dir  = "${path.module}/../lambda/detect-bronze-changes"
  timeout     = 60
  memory_size = 128
  codeblock   = "53-glue-etl-workflow"
  kms_key_arn = aws_kms_key.datalake.arn

  environment_variables = {
    REGISTRY_TABLE          = aws_dynamodb_table.data_source_registry.name
    DATALAKE_BUCKET         = module.datalake.bucket_id
    SILVER_TABLE_BUCKET_ARN = aws_s3tables_table_bucket.silver.arn
    GLUE_JOB_PREFIX         = "${var.PrefixCode}-glue-bronze-to-silver-"
  }

  additional_iam_statements = [
    {
      Effect   = "Allow"
      Action   = ["dynamodb:Scan"]
      Resource = aws_dynamodb_table.data_source_registry.arn
    },
    {
      Effect   = "Allow"
      Action   = ["s3:ListBucket"]
      Resource = module.datalake.bucket_arn
    },
    {
      Effect   = "Allow"
      Action   = ["s3tables:ListNamespaces", "s3tables:ListTables"]
      Resource = aws_s3tables_table_bucket.silver.arn
    },
    {
      Effect = "Allow"
      # nosemgrep: no-iam-resource-exposure, glue:ListJobs is account-level and only supports Resource=* (https://docs.aws.amazon.com/service-authorization/latest/reference/list_awsglue.html#awsglue-actions-as-permissions)
      Action   = ["glue:ListJobs"]
      Resource = "*"
    },
  ]
}

# Lambda: mark-silver-processed

module "mark_silver_processed" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "mark-silver-processed"
  source_dir  = "${path.module}/../lambda/mark-silver-processed"
  timeout     = 10
  memory_size = 128
  codeblock   = "53-glue-etl-workflow"
  kms_key_arn = aws_kms_key.datalake.arn

  environment_variables = {
    REGISTRY_TABLE = aws_dynamodb_table.data_source_registry.name
  }

  additional_iam_statements = [
    {
      Effect   = "Allow"
      Action   = ["dynamodb:UpdateItem"]
      Resource = aws_dynamodb_table.data_source_registry.arn
    },
  ]
}

# Step Function

# Transient Lambda service errors, the retry set AWS recommends for lambda:invoke
locals {
  lambda_retry = {
    ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"]
    IntervalSeconds = 2
    MaxAttempts     = 3
    BackoffRate     = 2
  }
}

resource "aws_sfn_state_machine" "etl_to_gold" {
  name     = "${var.PrefixCode}-sfn-etl-to-gold"
  role_arn = aws_iam_role.sfn_etl_to_gold.arn

  # CreateStateMachine checks the role can create the log delivery; the role alone doesn't imply its policy
  depends_on = [aws_iam_role_policy.sfn_etl_to_gold]

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_logs.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  tracing_configuration {
    enabled = true
  }

  definition = jsonencode({
    Comment = "Detect bronze changes, then if there is work: warm up Redshift, the bronze-to-silver jobs, silver-to-gold and the Redshift refresh for the changed tables, the Redshift gold views"
    StartAt = "DetectChanges"
    States = {
      # Input {"full": true} rebuilds every table, as do a fresh deployment and a new source
      DetectChanges = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = module.detect_bronze_changes.function_arn
          "Payload.$"  = "$"
        }
        ResultSelector = { "jobs.$" = "$.Payload.jobs", "scope.$" = "$.Payload.scope" }
        Retry          = [local.lambda_retry]
        Next           = "AnyWork"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "Failed"
        }]
      }

      # No changed bronze and not a full run: nothing in gold or Redshift is rebuilt and the area views stay up
      AnyWork = {
        Type = "Choice"
        Choices = [
          { Variable = "$.scope.full", BooleanEquals = true, Next = "WarmupRedshift" },
          { Variable = "$.jobs[0]", IsPresent = true, Next = "WarmupRedshift" },
        ]
        Default = "Done"
      }

      WarmupRedshift = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = module.redshift_setup.function_arn
          Payload = {
            action = "warmup"
          }
        }
        ResultPath     = "$.warmup"
        TimeoutSeconds = 960
        Next           = "AnyChanges"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.warmup_error"
          Next        = "AnyChanges"
        }]
      }

      AnyChanges = {
        Type = "Choice"
        Choices = [{
          Variable  = "$.jobs[0]"
          IsPresent = true
          Next      = "RunBronzeToSilver"
        }]
        Default = "SilverToGold"
      }

      RunBronzeToSilver = {
        Type           = "Map"
        ItemsPath      = "$.jobs"
        MaxConcurrency = 5
        ItemProcessor = {
          ProcessorConfig = { Mode = "INLINE" }
          StartAt         = "RunGlueJob"
          States = {
            RunGlueJob = {
              Type     = "Task"
              Resource = "arn:aws:states:::glue:startJobRun.sync"
              Parameters = {
                "JobName.$" = "$.glue_job_name"
              }
              ResultPath = "$.glue_result"
              Next       = "MarkProcessed"
              Catch = [{
                ErrorEquals = ["States.ALL"]
                ResultPath  = "$.error"
                Next        = "JobFailed"
              }]
            }
            MarkProcessed = {
              Type     = "Task"
              Resource = "arn:aws:states:::lambda:invoke"
              Parameters = {
                FunctionName = module.mark_silver_processed.function_arn
                Payload = {
                  "source_id.$"     = "$.source_id"
                  "first_run.$"     = "$.first_run"
                  "bronze_latest.$" = "$.bronze_latest"
                }
              }
              ResultPath = "$.mark"
              Retry      = [local.lambda_retry]
              Catch = [{
                ErrorEquals = ["States.ALL"]
                ResultPath  = "$.error"
                Next        = "JobFailed"
              }]
              End = true
            }
            JobFailed = {
              Type       = "Pass"
              Result     = true
              ResultPath = "$.failed"
              End        = true
            }
          }
        }
        ResultPath = "$.bronze_results"
        Next       = "CollectBronzeFailures"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "Failed"
        }]
      }

      # A failed bronze-to-silver job doesn't stop the run; its source id is kept and the run fails at the end
      CollectBronzeFailures = {
        Type = "Pass"
        Parameters = {
          "failed.$" = "$.bronze_results[?(@.failed == true)].source_id"
        }
        ResultPath = "$.bronze_check"
        Next       = "SilverToGold"
      }

      # Gold commits the tables that built before it fails; Redshift is still refreshed and the run fails at the end
      SilverToGold = {
        Type     = "Task"
        Resource = "arn:aws:states:::glue:startJobRun.sync"
        Parameters = {
          JobName   = aws_glue_job.silver_to_gold.name
          Arguments = { "--TABLES.$" = "$.scope.gold_tables" }
        }
        ResultPath = "$.gold"
        Next       = "RedshiftRefresh"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.gold_error"
          Next        = "RedshiftRefresh"
        }]
      }

      RedshiftRefresh = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = module.redshift_setup.function_arn
          # An empty list is the full refresh
          Payload = {
            action     = "refresh"
            "tables.$" = "$.scope.rs_tables"
          }
        }
        ResultPath     = "$.redshift_refresh"
        TimeoutSeconds = 960
        Retry          = [local.lambda_retry]
        Next           = "RedshiftGold"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "Failed"
        }]
      }

      RedshiftGold = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = module.redshift_setup.function_arn
          Payload = {
            action = "gold"
          }
        }
        ResultPath     = "$.redshift_gold"
        TimeoutSeconds = 960
        Retry          = [local.lambda_retry]
        Next           = "CheckFailures"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "Failed"
        }]
      }

      CheckFailures = {
        Type = "Choice"
        Choices = [
          {
            Variable  = "$.gold_error"
            IsPresent = true
            Next      = "SilverToGoldFailed"
          },
          {
            Variable  = "$.bronze_check.failed[0]"
            IsPresent = true
            Next      = "BronzeToSilverFailed"
          },
        ]
        Default = "Done"
      }

      SilverToGoldFailed = {
        Type      = "Fail"
        Error     = "SilverToGoldFailed"
        CausePath = "$.gold_error.Cause"
      }

      BronzeToSilverFailed = {
        Type      = "Fail"
        Error     = "BronzeToSilverFailed"
        CausePath = "States.Format('Bronze-to-silver jobs failed: {}', States.JsonToString($.bronze_check.failed))"
      }

      Done = {
        Type = "Succeed"
      }

      Failed = {
        Type      = "Fail"
        ErrorPath = "$.error.Error"
        CausePath = "$.error.Cause"
      }
    }
  })

  tags = {
    Name         = "${var.PrefixCode}-sfn-etl-to-gold"
    resourcetype = "compute"
    codeblock    = "53-glue-etl-workflow"
  }
}

# IAM

resource "aws_iam_role" "sfn_etl_to_gold" {
  name = "${var.PrefixCode}-iamrole-sfn-etl-to-gold"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.PrefixCode}-iamrole-sfn-etl-to-gold"
    resourcetype = "security"
    codeblock    = "53-glue-etl-workflow"
  }
}

resource "aws_iam_role_policy" "sfn_etl_to_gold" {
  #checkov:skip=CKV_AWS_355:Step Functions log delivery and X-Ray actions have no resource-level permissions (https://docs.aws.amazon.com/step-functions/latest/dg/cw-logs.html)
  name = "${var.PrefixCode}-policy-sfn-etl-to-gold"
  role = aws_iam_role.sfn_etl_to_gold.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(local.sfn_base_statements, [
      {
        Effect = "Allow"
        Action = ["lambda:InvokeFunction"]
        Resource = [
          module.detect_bronze_changes.function_arn,
          module.mark_silver_processed.function_arn,
          module.redshift_setup.function_arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"]
        Resource = "arn:aws:glue:${var.Region}:${data.aws_caller_identity.current.account_id}:job/${var.PrefixCode}-glue-*"
      }
    ])
  })
}

# ETL at 05:00 UTC, Monday to Saturday: rebuilds only the sources with new bronze data, or nothing
resource "aws_scheduler_schedule" "etl_to_gold_daily" {
  name        = "${var.PrefixCode}-schedule-etl-to-gold"
  group_name  = "default"
  kms_key_arn = aws_kms_key.datalake.arn

  flexible_time_window { mode = "OFF" }
  schedule_expression = "cron(0 5 ? * MON-SAT *)"

  target {
    arn      = aws_sfn_state_machine.etl_to_gold.arn
    role_arn = aws_iam_role.eventbridge_scheduler.arn
    input    = "{}"
  }
}

# Sunday 05:00 UTC: rebuilds every table, which applies changed gold and refresh code and repairs a failed run
resource "aws_scheduler_schedule" "etl_to_gold_weekly_full" {
  name        = "${var.PrefixCode}-schedule-etl-to-gold-full"
  group_name  = "default"
  kms_key_arn = aws_kms_key.datalake.arn

  flexible_time_window { mode = "OFF" }
  schedule_expression = "cron(0 5 ? * SUN *)"

  target {
    arn      = aws_sfn_state_machine.etl_to_gold.arn
    role_arn = aws_iam_role.eventbridge_scheduler.arn
    input    = jsonencode({ full = true })
  }
}
