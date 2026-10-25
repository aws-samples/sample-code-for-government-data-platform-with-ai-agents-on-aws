# CodePipeline bootstrap. The pipeline deploys from a CodeCommit repo on every push to codecommit_branch.
locals {
  terraform_version = "1.14"
  # Same version as plugin "aws" in .tflint.hcl
  tflint_ruleset_version = "0.49.0"
  # The image projects terraform-live creates (71-codebuild.tf); the Build stage runs them in parallel
  image_builds = toset(["agent", "agent-walkthrough", "agent-geospatial", "webapp", "dashboard"])
  source_action = {
    provider = "CodeCommit"
    configuration = {
      RepositoryName       = aws_codecommit_repository.main.repository_name
      BranchName           = var.codecommit_branch
      PollForSourceChanges = "false"
    }
  }
}
# KMS key for the artifact bucket

resource "aws_kms_key" "pipeline" {
  description             = "Encrypts the pipeline artifact bucket"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountRoot"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid    = "PipelineRoles"
        Effect = "Allow"
        Principal = {
          AWS = [
            aws_iam_role.pipeline.arn,
            aws_iam_role.pipeline_apply.arn,
          ]
        }
        Action = [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey",
          "kms:GenerateDataKeyWithoutPlaintext",
          "kms:ReEncryptFrom",
          "kms:ReEncryptTo",
          "kms:DescribeKey",
        ]
        Resource = "*"
      },
    ]
  })

  tags = {
    Name         = "${var.prefix_code}-kms-pipeline"
    resourcetype = "security"
    codeblock    = "pipeline"
  }
}

resource "aws_kms_alias" "pipeline" {
  name          = "alias/${var.prefix_code}-pipeline"
  target_key_id = aws_kms_key.pipeline.key_id
}

# Source: CodeCommit repo, push to it to trigger the pipeline

resource "aws_codecommit_repository" "main" {
  #checkov:skip=CKV2_AWS_37:The pipeline deploys from codecommit_branch, approval rules are not used
  repository_name = "${var.prefix_code}-source"
  description     = "Pipeline source for the Government Data Platform"

  tags = {
    Name         = "${var.prefix_code}-repo-source"
    resourcetype = "devtools"
    codeblock    = "pipeline"
  }
}

# Artifact bucket

# nosemgrep: aws-s3-bucket-versioning-not-enabled, versioning is set by aws_s3_bucket_versioning
resource "aws_s3_bucket" "pipeline_artifacts" {
  #checkov:skip=CKV2_AWS_61:Artifacts are small and overwritten each run, no lifecycle rule
  #checkov:skip=CKV_AWS_18:Access audited via CloudTrail
  #checkov:skip=CKV_AWS_144:Single-region deployment
  #checkov:skip=CKV_AWS_145:Encrypted via separate aws_s3_bucket_server_side_encryption_configuration resource (aws:kms + bucket_key)
  #checkov:skip=CKV2_AWS_62:Artifact bucket is read by CodePipeline directly, no event notifications needed
  bucket        = "${var.prefix_code}-pipeline-artifacts-${local.account_id}-${var.aws_region}"
  force_destroy = true

  tags = {
    Name         = "${var.prefix_code}-pipeline-artifacts"
    resourcetype = "storage"
    codeblock    = "pipeline"
  }
}

resource "aws_s3_bucket_versioning" "pipeline_artifacts" {
  bucket = aws_s3_bucket.pipeline_artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "pipeline_artifacts" {
  #checkov:skip=CKV2_AWS_67:aws_kms_key.pipeline has enable_key_rotation = true (Checkov cross-resource false positive)
  bucket = aws_s3_bucket.pipeline_artifacts.id
  rule {
    bucket_key_enabled       = true
    blocked_encryption_types = ["SSE-C"]
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.pipeline.arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "pipeline_artifacts" {
  bucket                  = aws_s3_bucket.pipeline_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Apply CodeBuild role

resource "aws_iam_role" "pipeline_apply" {
  name = "${var.prefix_code}-iamrole-pipeline-apply"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codebuild.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.prefix_code}-iamrole-pipeline-apply"
    resourcetype = "security"
    codeblock    = "pipeline"
  }
}

resource "aws_iam_role_policy_attachment" "pipeline_apply_networking" {
  role       = aws_iam_role.pipeline_apply.name
  policy_arn = aws_iam_policy.tf_networking.arn
}
resource "aws_iam_role_policy_attachment" "pipeline_apply_compute" {
  role       = aws_iam_role.pipeline_apply.name
  policy_arn = aws_iam_policy.tf_compute.arn
}
resource "aws_iam_role_policy_attachment" "pipeline_apply_data" {
  role       = aws_iam_role.pipeline_apply.name
  policy_arn = aws_iam_policy.tf_data.arn
}
resource "aws_iam_role_policy_attachment" "pipeline_apply_orchestration_ai" {
  role       = aws_iam_role.pipeline_apply.name
  policy_arn = aws_iam_policy.tf_orchestration_ai.arn
}
resource "aws_iam_role_policy_attachment" "pipeline_apply_security_obs" {
  role       = aws_iam_role.pipeline_apply.name
  policy_arn = aws_iam_policy.tf_security_obs.arn
}

resource "aws_iam_role_policy" "pipeline_apply" {
  name = "${var.prefix_code}-policy-pipeline-apply"
  role = aws_iam_role.pipeline_apply.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Logs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws/codebuild/*"
      },
      {
        Sid    = "ArtifactBucket"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:PutObject",
          "s3:ListBucket",
        ]
        Resource = [
          aws_s3_bucket.pipeline_artifacts.arn,
          "${aws_s3_bucket.pipeline_artifacts.arn}/*",
        ]
      },
      {
        Sid    = "KmsPipeline"
        Effect = "Allow"
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey",
        ]
        Resource = [aws_kms_key.pipeline.arn, aws_kms_key.tfstate.arn]
      },
    ]
  })
}

# Apply CodeBuild project with an inline buildspec; the Build and Deploy stages both run it and SOFT_FAIL toggles

resource "aws_cloudwatch_log_group" "pipeline_apply" {
  #checkov:skip=CKV_AWS_158:Default encryption with aws/logs is sufficient for pipeline build logs
  name              = "/aws/codebuild/${var.prefix_code}-codebuild-pipeline-apply"
  retention_in_days = 365

  tags = {
    Name         = "${var.prefix_code}-logs-pipeline-apply"
    resourcetype = "devtools"
    codeblock    = "pipeline"
  }
}

resource "aws_codebuild_project" "pipeline_apply" {
  #checkov:skip=CKV_AWS_316:No Docker build here, just terraform
  #checkov:skip=CKV_AWS_314:Logs go to the dedicated log group above
  name           = "${var.prefix_code}-codebuild-pipeline-apply"
  description    = "Runs terraform apply against deploy/terraform-live"
  service_role   = aws_iam_role.pipeline_apply.arn
  encryption_key = aws_kms_key.pipeline.arn
  build_timeout  = 60

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "PREFIX_CODE"
      value = var.prefix_code
    }
    environment_variable {
      name  = "AWS_REGION"
      value = var.aws_region
    }
    environment_variable {
      name  = "TF_STATE_BUCKET"
      value = aws_s3_bucket.tfstate.id
    }
    environment_variable {
      name  = "SOFT_FAIL"
      value = "false"
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = <<-EOT
      version: 0.2
      env:
        variables:
          TF_IN_AUTOMATION: "true"
          TERRAFORM_VERSION: "${local.terraform_version}"
          TF_STATE_KEY: "onegov-data-platform-public/terraform.tfstate"
      phases:
        install:
          commands:
            - yum install -y -q yum-utils
            - yum-config-manager --add-repo https://rpm.releases.hashicorp.com/AmazonLinux/hashicorp.repo
            - yum install -y -q terraform-$${TERRAFORM_VERSION}.*
            - terraform --version
        build:
          commands:
            - cd deploy/terraform-live
            - terraform init -backend-config="bucket=$${TF_STATE_BUCKET}" -backend-config="key=$${TF_STATE_KEY}" -backend-config="region=$${AWS_REGION}"
            - |
              set +e
              terraform apply -auto-approve \
                -var "PrefixCode=$${PREFIX_CODE}" \
                -var "Region=$${AWS_REGION}"
              RC=$?
              set -e
              if [ "$${SOFT_FAIL}" = "true" ] && [ $RC -ne 0 ]; then
                echo "First-pass apply exit $RC - expected on fresh accounts (images not yet pushed). Continuing to build stage."
                exit 0
              fi
              exit $RC
    EOT
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.pipeline_apply.name
    }
  }

  tags = {
    Name         = "${var.prefix_code}-codebuild-pipeline-apply"
    resourcetype = "devtools"
    codeblock    = "pipeline"
  }
}

# Manually-triggered teardown of terraform-live

resource "aws_cloudwatch_log_group" "teardown" {
  #checkov:skip=CKV_AWS_158:Default aws/logs encryption is sufficient for build logs
  name              = "/aws/codebuild/${var.prefix_code}-codebuild-teardown"
  retention_in_days = 365

  tags = {
    Name         = "${var.prefix_code}-logs-teardown"
    resourcetype = "monitoring"
    codeblock    = "pipeline"
  }
}

resource "aws_codebuild_project" "teardown" {
  #checkov:skip=CKV_AWS_316:No Docker build, just terraform destroy
  #checkov:skip=CKV_AWS_314:Logs go to the dedicated log group above
  name           = "${var.prefix_code}-codebuild-teardown"
  description    = "Teardown of deploy/terraform-live, run by the teardown pipeline after manual approval"
  service_role   = aws_iam_role.pipeline_apply.arn
  encryption_key = aws_kms_key.pipeline.arn
  build_timeout  = 60

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "PREFIX_CODE"
      value = var.prefix_code
    }
    environment_variable {
      name  = "AWS_REGION"
      value = var.aws_region
    }
    environment_variable {
      name  = "TF_STATE_BUCKET"
      value = aws_s3_bucket.tfstate.id
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = <<-EOT
      version: 0.2
      env:
        variables:
          TF_IN_AUTOMATION: "true"
          TERRAFORM_VERSION: "${local.terraform_version}"
          TF_STATE_KEY: "onegov-data-platform-public/terraform.tfstate"
      phases:
        install:
          commands:
            - yum install -y -q yum-utils
            - yum-config-manager --add-repo https://rpm.releases.hashicorp.com/AmazonLinux/hashicorp.repo
            - yum install -y -q terraform-$${TERRAFORM_VERSION}.*
        build:
          commands:
            - ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
            - |
              # Glue creates S3 Tables tables at runtime; empty namespaces so terraform can drop the buckets
              for layer in gold silver; do
                arn="arn:aws:s3tables:$${AWS_REGION}:$ACCOUNT_ID:bucket/$${PREFIX_CODE}-datalake-$layer-$ACCOUNT_ID"
                for ns in $(aws s3tables list-namespaces --table-bucket-arn "$arn" --region "$${AWS_REGION}" --query 'namespaces[].namespace[0]' --output text 2>/dev/null); do
                  for tbl in $(aws s3tables list-tables --table-bucket-arn "$arn" --namespace "$ns" --region "$${AWS_REGION}" --query 'tables[].name' --output text 2>/dev/null); do
                    aws s3tables delete-table --table-bucket-arn "$arn" --namespace "$ns" --name "$tbl" --region "$${AWS_REGION}" || true
                  done
                done
              done
            - cd deploy/terraform-live
            - terraform init -backend-config="bucket=$${TF_STATE_BUCKET}" -backend-config="key=$${TF_STATE_KEY}" -backend-config="region=$${AWS_REGION}"
            - terraform destroy -auto-approve -var "PrefixCode=$${PREFIX_CODE}" -var "Region=$${AWS_REGION}"
    EOT
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.teardown.name
    }
  }

  tags = {
    Name         = "${var.prefix_code}-codebuild-teardown"
    resourcetype = "devtools"
    codeblock    = "pipeline"
  }
}

# Teardown pipeline: Source then a manual approval gate (console Approve/Reject) then the destroy build
resource "aws_codepipeline" "teardown" {
  name           = "${var.prefix_code}-pipeline-teardown"
  role_arn       = aws_iam_role.pipeline.arn
  pipeline_type  = "V2"
  execution_mode = "QUEUED"

  artifact_store {
    type     = "S3"
    location = aws_s3_bucket.pipeline_artifacts.id

    encryption_key {
      id   = aws_kms_key.pipeline.arn
      type = "KMS"
    }
  }

  stage {
    name = "Source"

    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = local.source_action.provider
      version          = "1"
      output_artifacts = ["SourceCode"]
      configuration    = local.source_action.configuration
    }
  }

  stage {
    name = "Approve"

    action {
      name     = "ConfirmDestroy"
      category = "Approval"
      owner    = "AWS"
      provider = "Manual"
      version  = "1"
      configuration = {
        CustomData = "Approving DESTROYS the ${var.prefix_code} platform and all its data. There is no undo."
      }
    }
  }

  stage {
    name = "Teardown"

    action {
      name            = "destroy"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["SourceCode"]

      configuration = {
        ProjectName = aws_codebuild_project.teardown.name
      }
    }
  }

  tags = {
    Name         = "${var.prefix_code}-pipeline-teardown"
    resourcetype = "devtools"
    codeblock    = "pipeline"
  }
}

# Pipeline role

resource "aws_iam_role" "pipeline" {
  name = "${var.prefix_code}-iamrole-pipeline"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codepipeline.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.prefix_code}-iamrole-pipeline"
    resourcetype = "security"
    codeblock    = "pipeline"
  }
}

resource "aws_iam_role_policy" "pipeline" {
  #checkov:skip=CKV_AWS_355:cloudfront:ListDistributions has no resource-level permissions
  #checkov:skip=CKV_AWS_290:Pipeline role needs to start builds and manage artifacts
  name = "${var.prefix_code}-policy-pipeline"
  role = aws_iam_role.pipeline.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ArtifactBucket"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:GetBucketVersioning",
        ]
        Resource = [
          aws_s3_bucket.pipeline_artifacts.arn,
          "${aws_s3_bucket.pipeline_artifacts.arn}/*",
        ]
      },
      {
        Sid    = "KmsPipeline"
        Effect = "Allow"
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey",
        ]
        Resource = [aws_kms_key.pipeline.arn]
      },
      {
        Sid    = "CodeBuildApply"
        Effect = "Allow"
        Action = [
          "codebuild:StartBuild",
          "codebuild:StopBuild",
          "codebuild:BatchGetBuilds",
          "codebuild:BatchGetProjects",
        ]
        Resource = concat(
          [aws_codebuild_project.pipeline_apply.arn, aws_codebuild_project.teardown.arn],
          [for b in local.image_builds : "arn:aws:codebuild:${var.aws_region}:${local.account_id}:project/${var.prefix_code}-codebuild-${b}"],
        )
      },
      {
        # The pool id is generated by terraform-live; scoped to this account's user pools
        Sid      = "SmokeTestUserPassword"
        Effect   = "Allow"
        Action   = ["cognito-idp:AdminSetUserPassword"]
        Resource = "arn:aws:cognito-idp:${var.aws_region}:${local.account_id}:userpool/*"
      },
      {
        Sid    = "CommandsLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws/codepipeline/${var.prefix_code}-pipeline-deploy:*"
      },
      {
        Sid      = "SmokeDiscover"
        Effect   = "Allow"
        Action   = ["cloudfront:ListDistributions"]
        Resource = "*"
      },
      {
        Sid      = "SmokeCognitoConfig"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = "arn:aws:ssm:${var.aws_region}:${local.account_id}:parameter/${var.prefix_code}/*"
      },
      {
        # The datalake key lives in terraform-live; scoped by SSM and the one parameter it decrypts
        Sid      = "SmokeCognitoConfigDecrypt"
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = "arn:aws:kms:${var.aws_region}:${local.account_id}:key/*"
        Condition = {
          StringEquals = {
            "kms:ViaService"                      = "ssm.${var.aws_region}.amazonaws.com"
            "kms:EncryptionContext:PARAMETER_ARN" = "arn:aws:ssm:${var.aws_region}:${local.account_id}:parameter/${var.prefix_code}/cognito/config"
          }
        }
      },
      {
        Sid    = "SmokeBrowser"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:StartBrowserSession",
          "bedrock-agentcore:GetBrowserSession",
          "bedrock-agentcore:StopBrowserSession",
          "bedrock-agentcore:ConnectBrowserAutomationStream",
        ]
        Resource = [
          "arn:aws:bedrock-agentcore:${var.aws_region}:${local.account_id}:browser/*",
          "arn:aws:bedrock-agentcore:${var.aws_region}:aws:browser/*",
        ]
      },
      {
        Sid    = "SourceCodeCommit"
        Effect = "Allow"
        Action = [
          "codecommit:GetBranch",
          "codecommit:GetCommit",
          "codecommit:GetRepository",
          "codecommit:GetUploadArchiveStatus",
          "codecommit:UploadArchive",
          "codecommit:CancelUploadArchive",
        ]
        Resource = aws_codecommit_repository.main.arn
      },
    ]
  })
}

# Pipeline, V2

resource "aws_codepipeline" "main" {
  name           = "${var.prefix_code}-pipeline-deploy"
  role_arn       = aws_iam_role.pipeline.arn
  pipeline_type  = "V2"
  execution_mode = "SUPERSEDED"

  artifact_store {
    type     = "S3"
    location = aws_s3_bucket.pipeline_artifacts.id

    encryption_key {
      id   = aws_kms_key.pipeline.arn
      type = "KMS"
    }
  }

  stage {
    name = "Source"

    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = local.source_action.provider
      version          = "1"
      output_artifacts = ["SourceCode"]
      configuration    = local.source_action.configuration
    }
  }

  stage {
    name = "Validate"

    action {
      name            = "lint-terraform"
      category        = "Compute"
      owner           = "AWS"
      provider        = "Commands"
      version         = "1"
      input_artifacts = ["SourceCode"]

      commands = [
        "yum install -y -q yum-utils unzip",
        "curl -fsSLO https://github.com/terraform-linters/tflint/releases/download/v0.64.0/tflint_linux_amd64.zip",
        "unzip -o tflint_linux_amd64.zip -d /usr/local/bin/ && rm tflint_linux_amd64.zip",
        # The tflint ruleset is installed from its release zip rather than by tflint --init
        "mkdir -p ~/.tflint.d/plugins/github.com/terraform-linters/tflint-ruleset-aws/${local.tflint_ruleset_version}",
        "curl -fsSLO https://github.com/terraform-linters/tflint-ruleset-aws/releases/download/v${local.tflint_ruleset_version}/tflint-ruleset-aws_linux_amd64.zip",
        "unzip -o tflint-ruleset-aws_linux_amd64.zip -d ~/.tflint.d/plugins/github.com/terraform-linters/tflint-ruleset-aws/${local.tflint_ruleset_version}/ && rm tflint-ruleset-aws_linux_amd64.zip",
        "yum-config-manager --add-repo https://rpm.releases.hashicorp.com/AmazonLinux/hashicorp.repo",
        "yum install -y -q terraform-${local.terraform_version}.*",
        "export TFLINT_CONFIG_FILE=$CODEBUILD_SRC_DIR/.tflint.hcl",
        "cd deploy/terraform-live",
        "tflint --init && tflint --recursive",
        "terraform init -backend=false -input=false > /dev/null",
        "terraform fmt -check -recursive",
        "terraform validate",
        "cd ../../bootstrap",
        "tflint",
        "terraform init -backend=false -input=false > /dev/null",
        "terraform fmt -check",
        "terraform validate",
      ]
    }
  }

  # Run order 1 applies the Terraform the images need (ECR, roles, SSM); it soft-fails on a fresh account where the
  # runtimes still point at images that don't exist. Run order 2 builds the five images in parallel.
  stage {
    name = "Build"

    action {
      name            = "terraform-apply"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      run_order       = 1
      input_artifacts = ["SourceCode"]

      configuration = {
        ProjectName = aws_codebuild_project.pipeline_apply.name
        EnvironmentVariables = jsonencode([
          { name = "SOFT_FAIL", value = "true", type = "PLAINTEXT" },
        ])
      }
    }

    dynamic "action" {
      for_each = local.image_builds
      content {
        name            = "build-${action.value}"
        category        = "Build"
        owner           = "AWS"
        provider        = "CodeBuild"
        version         = "1"
        run_order       = 2
        input_artifacts = ["SourceCode"]
        configuration = {
          ProjectName = "${var.prefix_code}-codebuild-${action.value}"
        }
      }
    }
  }

  # The same apply again, now that the image tags are in SSM; this one must succeed
  stage {
    name = "Deploy"

    action {
      name            = "terraform-apply"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["SourceCode"]

      configuration = {
        ProjectName = aws_codebuild_project.pipeline_apply.name
        EnvironmentVariables = jsonencode([
          { name = "SOFT_FAIL", value = "false", type = "PLAINTEXT" },
        ])
      }
    }
  }

  stage {
    name = "Test"

    action {
      name            = "browser-smoke-test"
      category        = "Compute"
      owner           = "AWS"
      provider        = "Commands"
      version         = "1"
      input_artifacts = ["SourceCode"]

      commands = [
        "bash -c 'set +e; yum install -y -q python3.12 python3.12-pip && python3.12 -m pip install -q uv && AWS_REGION=${var.aws_region} PREFIX_CODE=${var.prefix_code} uv run tests/browser_smoke_test.py --audit; RC=$?; echo \"Smoke test exit $RC (soft-fail)\"; exit 0'",
      ]
    }
  }

  tags = {
    Name         = "${var.prefix_code}-pipeline-deploy"
    resourcetype = "devtools"
    codeblock    = "pipeline"
  }
}

# EventBridge starts the pipeline on a push to the CodeCommit branch

resource "aws_iam_role" "eventbridge_pipeline" {
  name = "${var.prefix_code}-iamrole-eventbridge-pipeline"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.prefix_code}-iamrole-eventbridge-pipeline"
    resourcetype = "security"
    codeblock    = "pipeline"
  }
}

resource "aws_iam_role_policy" "eventbridge_pipeline" {
  name = "${var.prefix_code}-policy-eventbridge-pipeline"
  role = aws_iam_role.eventbridge_pipeline.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["codepipeline:StartPipelineExecution"]
      Resource = aws_codepipeline.main.arn
    }]
  })
}

# Start the pipeline on a push to the watched branch
resource "aws_cloudwatch_event_rule" "pipeline_source_codecommit" {
  name        = "${var.prefix_code}-event-pipeline-codecommit"
  description = "Start the deploy pipeline on push to the watched CodeCommit branch"

  event_pattern = jsonencode({
    source      = ["aws.codecommit"]
    detail-type = ["CodeCommit Repository State Change"]
    resources   = [aws_codecommit_repository.main.arn]
    detail = {
      event         = ["referenceCreated", "referenceUpdated"]
      referenceType = ["branch"]
      referenceName = [var.codecommit_branch]
    }
  })

  tags = {
    Name         = "${var.prefix_code}-event-pipeline-codecommit"
    resourcetype = "devtools"
    codeblock    = "pipeline"
  }
}

resource "aws_cloudwatch_event_target" "pipeline_source_codecommit" {
  rule     = aws_cloudwatch_event_rule.pipeline_source_codecommit.name
  arn      = aws_codepipeline.main.arn
  role_arn = aws_iam_role.eventbridge_pipeline.arn
}

# Outputs

output "tfstate_bucket" {
  description = "S3 bucket for Terraform state"
  value       = aws_s3_bucket.tfstate.id
}


output "pipeline_console_url" {
  description = "Console URL for the pipeline"
  value       = "https://${var.aws_region}.console.aws.amazon.com/codesuite/codepipeline/pipelines/${aws_codepipeline.main.name}/view?region=${var.aws_region}"
}

output "codecommit_clone_url_http" {
  description = "CodeCommit HTTPS clone URL"
  value       = aws_codecommit_repository.main.clone_url_http
}
