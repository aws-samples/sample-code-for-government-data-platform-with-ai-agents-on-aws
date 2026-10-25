# Step Function orchestrating all data source ingestion into Bronze

# Shared log group for all Step Function execution logs
resource "aws_cloudwatch_log_group" "sfn_logs" {
  name              = "/aws/states/${var.PrefixCode}-sfn"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.datalake.arn

  tags = {
    Name         = "${var.PrefixCode}-logs-sfn"
    resourcetype = "monitoring"
    codeblock    = "20-ingest-orchestrator"
  }
}

# Statements every Step Functions role needs: log delivery to the shared log group and X-Ray tracing
locals {
  sfn_base_statements = [
    {
      Effect = "Allow"
      # nosemgrep: no-iam-resource-exposure, logs:PutResourcePolicy requires Resource=* (https://docs.aws.amazon.com/step-functions/latest/dg/cw-logs.html)
      Action = [
        "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery",
        "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"
      ]
      Resource = "*"
    },
    {
      Effect   = "Allow"
      Action   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
      Resource = "*"
    },
  ]
}

# Every ingest source by router key, for the router, the ingest IAM, the schedules (06:00 UTC after the publisher's release, null for by hand) and the registry
locals {
  ingest_sources = {
    # data.police.uk has no release calendar and runs 7 to 8 weeks behind; a run fetches the last 12 months
    crime            = { type = "step-function", arn = aws_sfn_state_machine.police_ingestion.arn, source_id = "police-crime", schedule = "cron(0 6 5 * ? *)" }
    land-registry    = { type = "step-function", arn = aws_sfn_state_machine.land_registry_ingestion.arn, source_id = "land-registry", schedule = "cron(0 6 3 * ? *)" }       # 20th working day
    earnings         = { type = "lambda", arn = module.ingest_ons_earnings.function_arn, source_id = "ons-earnings", schedule = "cron(0 6 1 11 ? *)" }                        # ASHE, late October
    population       = { type = "lambda", arn = module.ingest_ons_population.function_arn, source_id = "ons-population", schedule = "cron(0 6 5 8,10 ? *)" }                  # England and Wales late July, UK early October
    wellbeing        = { type = "lambda", arn = module.ingest_ons_wellbeing.function_arn, source_id = "ons-wellbeing", schedule = "cron(0 6 1 10-12 ? *)" }                   # September to November
    ons-hpi          = { type = "lambda", arn = module.ingest_ons_hpi.function_arn, source_id = "ons-hpi", schedule = "cron(0 6 25 * ? *)" }                                  # third or fourth Wednesday
    schools          = { type = "lambda", arn = module.ingest_dfe_school_performance.function_arn, source_id = "dfe-school-performance", schedule = "cron(0 6 20 2,10 ? *)" } # provisional mid-October, revised early February
    nhs-rtt          = { type = "lambda", arn = module.ingest_nhs_rtt.function_arn, source_id = "nhs-rtt-waiting-times", schedule = "cron(0 6 16 * ? *)" }                    # second Thursday
    nhs-ods          = { type = "lambda", arn = module.ingest_nhs_ods.function_arn, source_id = "nhs-ods", schedule = "cron(0 6 1 * ? *)" }                                   # refreshed nightly
    hmrc-trade       = { type = "lambda", arn = module.ingest_hmrc_trade.function_arn, source_id = "hmrc-trade", schedule = "cron(0 6 25 3,6,9,12 ? *)" }                     # mid-month Thursday
    universal-credit = { type = "lambda", arn = module.ingest_dwp_universal_credit.function_arn, source_id = "dwp-universal-credit", schedule = "cron(0 6 25 2,5,8,11 ? *)" } # second or third Tuesday
    pip              = { type = "lambda", arn = module.ingest_dwp_pip.function_arn, source_id = "dwp-pip", schedule = "cron(0 6 25 3,6,9,12 ? *)" }                           # third Tuesday
    housing-benefit  = { type = "lambda", arn = module.ingest_dwp_housing_benefit.function_arn, source_id = "dwp-housing-benefit", schedule = "cron(0 6 1 10 ? *)" }          # annual, mid to late September
    cilif            = { type = "lambda", arn = module.ingest_dwp_cilif.function_arn, source_id = "dwp-cilif", schedule = "cron(0 6 5 4 ? *)" }                               # late March

    geography         = { type = "lambda", arn = module.ingest_geography_reference.function_arn, source_id = "ons-geography", schedule = null }
    school-detail     = { type = "lambda", arn = module.ingest_dfe_school_detail.function_arn, source_id = "dfe-school-detail", schedule = null }
    claimant-count    = { type = "lambda", arn = module.ingest_nomis_claimant_count.function_arn, source_id = "nomis-claimant-count", schedule = null }
    employment        = { type = "lambda", arn = module.ingest_ons_employment.function_arn, source_id = "ons-employment", schedule = null }
    deprivation       = { type = "lambda", arn = module.ingest_mhclg_deprivation.function_arn, source_id = "mhclg-deprivation", schedule = null }
    road-traffic      = { type = "lambda", arn = module.ingest_dft_road_traffic.function_arn, source_id = "dft-road-traffic", schedule = null }
    aps               = { type = "lambda", arn = module.ingest_nomis_aps.function_arn, source_id = "nomis-aps", schedule = null }
    gva               = { type = "lambda", arn = module.ingest_ons_gva.function_arn, source_id = "ons-gva", schedule = null }
    defra-air-quality = { type = "lambda", arn = module.ingest_defra_air_quality.function_arn, source_id = "defra-air-quality", schedule = null }
    mhclg-spending    = { type = "lambda", arn = module.ingest_mhclg_spending.function_arn, source_id = "mhclg-spending", schedule = null }
    jobs-density      = { type = "lambda", arn = module.ingest_jobs_density.function_arn, source_id = "jobs-density", schedule = null }
    business-counts   = { type = "lambda", arn = module.ingest_business_counts.function_arn, source_id = "business-counts", schedule = null }
    births-deaths     = { type = "lambda", arn = module.ingest_ons_births_deaths.function_arn, source_id = "ons-births-deaths", schedule = null }
  }

  ingest_schedules = { for key, s in local.ingest_sources : key => s if s.schedule != null }
}

# Resolves source keys to the Lambda names and state machine ARNs to run
module "ingest_router" {
  source = "./modules/lambda_function"

  prefix_code = var.PrefixCode
  name        = "ingest-router"
  source_dir  = "${path.module}/../lambda/ingest-router"
  timeout     = 10
  memory_size = 128
  codeblock   = "20-ingest-orchestrator"
  kms_key_arn = aws_kms_key.datalake.arn

  # Lambda names (the ARN's last field) rather than ARNs keep the variable under the 4 KB environment limit
  environment_variables = {
    SOURCES_JSON = jsonencode({ for key, s in local.ingest_sources : key => [s.type, s.type == "lambda" ? element(split(":", s.arn), 6) : s.arn] })
  }
}

# Publishers return 5xx and time out now and then, Stat-Xplore especially: three tries, a minute then two minutes apart
locals {
  ingest_retry = { ErrorEquals = ["States.TaskFailed"], IntervalSeconds = 60, MaxAttempts = 2, BackoffRate = 2 }
}

resource "aws_sfn_state_machine" "ingest_all" {
  name     = "${var.PrefixCode}-sfn-ingest-all"
  role_arn = aws_iam_role.sfn_ingest_all.arn

  depends_on = [aws_iam_role_policy.sfn_ingest_all]

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_logs.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  tracing_configuration {
    enabled = true
  }

  definition = jsonencode({
    Comment = "Orchestrate ingestion of selected or all data sources into Bronze"
    StartAt = "Route"
    States = {
      Route = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = module.ingest_router.function_arn
          "Payload.$"  = "$"
        }
        ResultSelector = { "tasks.$" = "$.Payload.tasks" }
        Next           = "RunAll"
      }
      RunAll = {
        Type           = "Map"
        ItemsPath      = "$.tasks"
        MaxConcurrency = 5
        ItemProcessor = {
          ProcessorConfig = { Mode = "INLINE" }
          StartAt         = "CheckType"
          States = {
            CheckType = {
              Type = "Choice"
              Choices = [{
                Variable     = "$.type"
                StringEquals = "step-function"
                Next         = "RunStepFunction"
              }]
              Default = "RunLambda"
            }
            # ResultPath keeps the task's name and arn beside its result
            RunStepFunction = {
              Type     = "Task"
              Resource = "arn:aws:states:::states:startExecution.sync:2"
              Parameters = {
                "StateMachineArn.$" = "$.arn"
                Input               = "{}"
              }
              ResultPath = "$.result"
              Retry      = [local.ingest_retry]
              Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "Failed" }]
              End        = true
            }
            RunLambda = {
              Type     = "Task"
              Resource = "arn:aws:states:::lambda:invoke"
              Parameters = {
                "FunctionName.$" = "$.arn"
                Payload          = {}
              }
              ResultPath = "$.result"
              Retry      = [local.ingest_retry]
              Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "Failed" }]
              End        = true
            }
            # A failed source is recorded and the other sources carry on; the run fails at the end
            Failed = { Type = "Pass", Result = true, ResultPath = "$.failed", End = true }
          }
        }
        ResultPath = "$.tasks"
        Next       = "CollectFailures"
      }
      CollectFailures = {
        Type = "Pass"
        Parameters = {
          "tasks.$"  = "$.tasks"
          "failed.$" = "$.tasks[?(@.failed == true)].name"
        }
        Next = "AnyFailed"
      }
      AnyFailed = {
        Type    = "Choice"
        Choices = [{ Variable = "$.failed[0]", IsPresent = true, Next = "SourcesFailed" }]
        Default = "Done"
      }
      SourcesFailed = {
        Type      = "Fail"
        Error     = "SourcesFailed"
        CausePath = "States.Format('Sources failed after retries: {}. The other sources landed in bronze.', States.JsonToString($.failed))"
      }
      Done = { Type = "Succeed" }
    }
  })

  tags = {
    Name         = "${var.PrefixCode}-sfn-ingest-all"
    resourcetype = "compute"
    codeblock    = "20-ingest-orchestrator"
  }
}

resource "aws_iam_role" "sfn_ingest_all" {
  name = "${var.PrefixCode}-iamrole-sfn-ingest-all"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.PrefixCode}-iamrole-sfn-ingest-all"
    resourcetype = "security"
    codeblock    = "20-ingest-orchestrator"
  }
}

resource "aws_iam_role_policy" "sfn_ingest_all" {
  #checkov:skip=CKV_AWS_355:Step Functions log delivery and X-Ray actions have no resource-level permissions (https://docs.aws.amazon.com/step-functions/latest/dg/cw-logs.html)
  name = "${var.PrefixCode}-policy-sfn-ingest-all"
  role = aws_iam_role.sfn_ingest_all.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(local.sfn_base_statements, [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = concat([module.ingest_router.function_arn], [for s in values(local.ingest_sources) : s.arn if s.type == "lambda"])
      },
      {
        Effect   = "Allow"
        Action   = ["states:StartExecution", "states:DescribeExecution", "states:StopExecution"]
        Resource = [for s in values(local.ingest_sources) : s.arn if s.type == "step-function"]
      },
      {
        Effect   = "Allow"
        Action   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
        Resource = "arn:aws:events:${var.Region}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventsForStepFunctionsExecutionRule"
      },
    ])
  })
}
