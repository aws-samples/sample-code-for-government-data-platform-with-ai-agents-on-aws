# CodeBuild projects that build the container images and push them to ECR, run in parallel by the pipeline's Build stage

locals {
  # One entry per image: the project suffix, its ECR repository and the deploy/ folder holding the buildspec
  image_builds = {
    agent             = { repo = aws_ecr_repository.agent, source = "agent-main" }
    agent-walkthrough = { repo = aws_ecr_repository.agent_walkthrough, source = "agent-walkthrough" }
    agent-geospatial  = { repo = aws_ecr_repository.agent_geospatial, source = "agent-geospatial" }
    webapp            = { repo = aws_ecr_repository.webapp, source = "webapp" }
    dashboard         = { repo = aws_ecr_repository.dashboard, source = "dashboard" }
  }
}

# IAM role for CodeBuild
resource "aws_iam_role" "codebuild" {
  name = "${var.PrefixCode}-iamrole-codebuild"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codebuild.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.PrefixCode}-iamrole-codebuild"
    resourcetype = "security"
    codeblock    = "71-codebuild"
  }
}

resource "aws_iam_role_policy" "codebuild" {
  #checkov:skip=CKV_AWS_287:ecr:GetAuthorizationToken requires Resource=*, account-level API (https://docs.aws.amazon.com/AmazonECR/latest/APIReference/API_GetAuthorizationToken.html)
  #checkov:skip=CKV_AWS_355:ECR and CloudWatch Logs actions require Resource=*
  #checkov:skip=CKV_AWS_290:CodeBuild needs write access to ECR (push images) and CloudWatch Logs
  name = "${var.PrefixCode}-policy-codebuild"
  role = aws_iam_role.codebuild.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ECRAuth"
        Effect = "Allow"
        # nosemgrep: no-iam-creds-exposure, ecr:GetAuthorizationToken is account-level, Resource=* required
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "ECRImage"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:DescribeImages",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload"
        ]
        Resource = [for b in local.image_builds : b.repo.arn]
      },
      {
        Sid    = "PipelineArtifactsRead"
        Effect = "Allow"
        # nosemgrep: no-iam-data-exfiltration, scoped to the pipeline artifact bucket for source artifact download
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
        ]
        Resource = "arn:aws:s3:::${var.PrefixCode}-pipeline-artifacts-${data.aws_caller_identity.current.account_id}-${var.Region}/*"
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = [for g in aws_cloudwatch_log_group.codebuild : "${g.arn}:*"]
      },
      {
        Sid    = "KMS"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey"
        ]
        Resource = aws_kms_key.datalake.arn
      },
      {
        # The pipeline key lives in bootstrap state; matched by alias rather than ARN
        Sid      = "PipelineArtifactsKMS"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:DescribeKey"]
        Resource = "arn:aws:kms:${var.Region}:${data.aws_caller_identity.current.account_id}:key/*"
        Condition = {
          "ForAnyValue:StringEquals" = {
            "kms:ResourceAliases" = "alias/${var.PrefixCode}-pipeline"
          }
        }
      },
      {
        Sid      = "SSMImageTags"
        Effect   = "Allow"
        Action   = ["ssm:PutParameter"]
        Resource = "arn:aws:ssm:${var.Region}:${data.aws_caller_identity.current.account_id}:parameter/${var.PrefixCode}/*-image-tag"
      }
    ]
  })
}

# Pre-created with retention and KMS; CodeBuild would otherwise create them unencrypted and never-expiring
resource "aws_cloudwatch_log_group" "codebuild" {
  for_each          = local.image_builds
  name              = "/aws/codebuild/${var.PrefixCode}-codebuild-${each.key}"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.datalake.arn

  tags = {
    Name         = "${var.PrefixCode}-logs-codebuild-${each.key}"
    resourcetype = "monitoring"
    codeblock    = "71-codebuild"
  }
}

# ARM64 builds: AgentCore runtimes and the Fargate tasks both run arm64 images
resource "aws_codebuild_project" "image" {
  #checkov:skip=CKV_AWS_316:Privileged mode required for Docker-in-Docker container builds
  for_each       = local.image_builds
  name           = "${var.PrefixCode}-codebuild-${each.key}"
  description    = "Build and push the ${each.key} container image to ECR"
  service_role   = aws_iam_role.codebuild.arn
  encryption_key = aws_kms_key.datalake.arn

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/amazonlinux-aarch64-standard:3.0"
    type                        = "ARM_CONTAINER"
    privileged_mode             = true
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "ECR_REPO"
      value = each.value.repo.repository_url
    }

    environment_variable {
      name  = "AWS_ACCOUNT_ID"
      value = data.aws_caller_identity.current.account_id
    }

    environment_variable {
      name  = "AWS_DEFAULT_REGION"
      value = var.Region
    }

    environment_variable {
      name  = "PREFIX_CODE"
      value = var.PrefixCode
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "deploy/${each.value.source}/buildspec.yml"
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.codebuild[each.key].name
    }
  }

  tags = {
    Name         = "${var.PrefixCode}-codebuild-${each.key}"
    resourcetype = "compute"
    codeblock    = "71-codebuild"
  }
}
