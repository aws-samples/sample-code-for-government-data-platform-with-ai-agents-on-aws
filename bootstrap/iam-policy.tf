# Scoped IAM policies for the apply role, split by layer to stay under the 6144-byte managed-policy limit.
# To extend: run `terraform plan` in deploy/terraform-live/; on AccessDenied, add the action to the relevant statement.

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = var.aws_region
  prefix     = var.prefix_code
}

# Policy 1: Networking (VPC, ALB, CloudFront)

resource "aws_iam_policy" "tf_networking" {
  #checkov:skip=CKV_AWS_355:ec2:Describe*, elb:* and the CloudFront actions have no resource-level permissions
  #checkov:skip=CKV_AWS_290:CI/CD role needs write access to deploy infrastructure
  name = "${var.prefix_code}-tf-networking"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EC2VPC"
        Effect = "Allow"
        Action = [
          "ec2:CreateVpc", "ec2:DeleteVpc", "ec2:DescribeVpcs", "ec2:ModifyVpcAttribute",
          "ec2:CreateSubnet", "ec2:DeleteSubnet", "ec2:DescribeSubnets",
          "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup", "ec2:DescribeSecurityGroups",
          "ec2:AuthorizeSecurityGroupIngress", "ec2:RevokeSecurityGroupIngress",
          "ec2:AuthorizeSecurityGroupEgress", "ec2:RevokeSecurityGroupEgress",
          "ec2:DescribeSecurityGroupRules",
          "ec2:CreateInternetGateway", "ec2:DeleteInternetGateway", "ec2:DescribeInternetGateways",
          "ec2:AttachInternetGateway", "ec2:DetachInternetGateway",
          "ec2:AllocateAddress", "ec2:ReleaseAddress", "ec2:DescribeAddresses", "ec2:DisassociateAddress",
          "ec2:CreateNatGateway", "ec2:DeleteNatGateway", "ec2:DescribeNatGateways",
          "ec2:CreateRouteTable", "ec2:DeleteRouteTable", "ec2:DescribeRouteTables",
          "ec2:CreateRoute", "ec2:DeleteRoute", "ec2:ReplaceRoute",
          "ec2:AssociateRouteTable", "ec2:DisassociateRouteTable",
          "ec2:CreateVpcEndpoint", "ec2:DeleteVpcEndpoints", "ec2:DescribeVpcEndpoints",
          "ec2:ModifyVpcEndpoint",
          "ec2:CreateFlowLogs", "ec2:DeleteFlowLogs", "ec2:DescribeFlowLogs",
          "ec2:CreateTags", "ec2:DeleteTags", "ec2:DescribeTags",
          "ec2:DescribeAvailabilityZones", "ec2:DescribeNetworkInterfaces",
          "ec2:DetachNetworkInterface", "ec2:DeleteNetworkInterface",
          "ec2:DescribePrefixLists", "ec2:DescribeManagedPrefixLists",
          "ec2:GetManagedPrefixListEntries",
          "ec2:DescribeAccountAttributes", "ec2:DescribeNetworkAcls",
          "ec2:DescribeVpcAttribute", "ec2:DescribeAddressesAttribute"
        ]
        Resource = "*"
      },
      {
        Sid    = "ELB"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:CreateLoadBalancer", "elasticloadbalancing:DeleteLoadBalancer",
          "elasticloadbalancing:DescribeLoadBalancers", "elasticloadbalancing:DescribeLoadBalancerAttributes",
          "elasticloadbalancing:ModifyLoadBalancerAttributes",
          "elasticloadbalancing:CreateTargetGroup", "elasticloadbalancing:DeleteTargetGroup",
          "elasticloadbalancing:DescribeTargetGroups", "elasticloadbalancing:DescribeTargetGroupAttributes",
          "elasticloadbalancing:ModifyTargetGroupAttributes", "elasticloadbalancing:ModifyTargetGroup",
          "elasticloadbalancing:DescribeTargetHealth",
          "elasticloadbalancing:CreateListener", "elasticloadbalancing:DeleteListener",
          "elasticloadbalancing:DescribeListeners", "elasticloadbalancing:ModifyListener",
          "elasticloadbalancing:CreateRule", "elasticloadbalancing:DeleteRule",
          "elasticloadbalancing:DescribeRules", "elasticloadbalancing:ModifyRule",
          "elasticloadbalancing:RegisterTargets", "elasticloadbalancing:DeregisterTargets",
          "elasticloadbalancing:AddTags", "elasticloadbalancing:RemoveTags",
          "elasticloadbalancing:DescribeTags", "elasticloadbalancing:SetSecurityGroups",
          "elasticloadbalancing:SetRulePriorities",
          "elasticloadbalancing:DescribeListenerAttributes"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudFront"
        Effect = "Allow"
        Action = [
          "cloudfront:CreateDistribution", "cloudfront:DeleteDistribution",
          "cloudfront:GetDistribution", "cloudfront:GetDistributionConfig",
          "cloudfront:UpdateDistribution", "cloudfront:ListDistributions",
          "cloudfront:TagResource", "cloudfront:UntagResource", "cloudfront:ListTagsForResource"
        ]
        Resource = "*"
      }
    ]
  })
  tags = {
    Name         = "${local.prefix}-policy-tf-networking"
    resourcetype = "security"
    codeblock    = "iam-policy"
  }

}

# Policy 2: Compute (ECS, ECR, Lambda, CodeBuild)

resource "aws_iam_policy" "tf_compute" {
  #checkov:skip=CKV_AWS_355:ecs:* requires Resource=*, ecr:GetAuthorizationToken requires Resource=*
  #checkov:skip=CKV_AWS_290:CI/CD role needs write access to deploy infrastructure
  #checkov:skip=CKV_AWS_287:ecr:GetAuthorizationToken requires Resource=*
  name = "${var.prefix_code}-tf-compute"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ECS"
        Effect = "Allow"
        Action = [
          "ecs:CreateCluster", "ecs:DeleteCluster", "ecs:DescribeClusters",
          "ecs:UpdateCluster", "ecs:PutClusterCapacityProviders",
          "ecs:CreateService", "ecs:DeleteService", "ecs:DescribeServices", "ecs:UpdateService",
          "ecs:RegisterTaskDefinition", "ecs:DeregisterTaskDefinition",
          "ecs:DescribeTaskDefinition", "ecs:ListTaskDefinitions",
          "ecs:ListTasks", "ecs:DescribeTasks",
          "ecs:TagResource", "ecs:UntagResource", "ecs:ListTagsForResource",
          "ecs:UpdateClusterSettings"
        ]
        Resource = "*"
      },
      {
        Sid      = "ECRAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "ECRRepos"
        Effect = "Allow"
        Action = [
          "ecr:CreateRepository", "ecr:DeleteRepository", "ecr:DescribeRepositories",
          "ecr:GetRepositoryPolicy", "ecr:SetRepositoryPolicy", "ecr:DeleteRepositoryPolicy",
          "ecr:ListImages", "ecr:DescribeImages",
          "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
          "ecr:PutImage", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload", "ecr:BatchCheckLayerAvailability",
          "ecr:PutLifecyclePolicy", "ecr:GetLifecyclePolicy",
          "ecr:PutImageScanningConfiguration", "ecr:PutImageTagMutability",
          "ecr:TagResource", "ecr:UntagResource", "ecr:ListTagsForResource",
          "ecr:BatchDeleteImage"
        ]
        Resource = "arn:aws:ecr:${local.region}:${local.account_id}:repository/${local.prefix}/*"
      },
      {
        Sid    = "Lambda"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction", "lambda:DeleteFunction", "lambda:GetFunction",
          "lambda:GetFunctionConfiguration", "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "lambda:AddPermission", "lambda:RemovePermission", "lambda:GetPolicy",
          "lambda:InvokeFunction",
          "lambda:PutFunctionConcurrency", "lambda:DeleteFunctionConcurrency",
          "lambda:GetFunctionConcurrency",
          "lambda:TagResource", "lambda:UntagResource", "lambda:ListTags",
          "lambda:ListVersionsByFunction", "lambda:GetFunctionCodeSigningConfig"
        ]
        Resource = "arn:aws:lambda:*:${local.account_id}:function:${local.prefix}-*"
      },
      {
        # Code shared between ingest Lambdas ships as a layer
        Sid    = "LambdaLayers"
        Effect = "Allow"
        Action = [
          "lambda:PublishLayerVersion", "lambda:GetLayerVersion", "lambda:DeleteLayerVersion",
          "lambda:ListLayerVersions"
        ]
        Resource = [
          "arn:aws:lambda:*:${local.account_id}:layer:${local.prefix}-*",
          "arn:aws:lambda:*:${local.account_id}:layer:${local.prefix}-*:*"
        ]
      },
      {
        Sid    = "CodeBuild"
        Effect = "Allow"
        Action = [
          "codebuild:CreateProject", "codebuild:DeleteProject",
          "codebuild:UpdateProject", "codebuild:BatchGetProjects",
          "codebuild:StartBuild", "codebuild:BatchGetBuilds",
          "codebuild:ListBuildsForProject"
        ]
        Resource = "arn:aws:codebuild:${local.region}:${local.account_id}:project/${local.prefix}-*"
      }
    ]
  })
  tags = {
    Name         = "${local.prefix}-policy-tf-compute"
    resourcetype = "security"
    codeblock    = "iam-policy"
  }

}

# Policy 3: Data (S3, DynamoDB, Glue, Redshift)

resource "aws_iam_policy" "tf_data" {
  #checkov:skip=CKV_AWS_355:glue:* and redshift-serverless:* require Resource=*
  #checkov:skip=CKV_AWS_290:CI/CD role needs write access to deploy infrastructure
  #checkov:skip=CKV_AWS_287:redshift-serverless:GetCredentials needed for Redshift Data API, scoped to workgroup prefix
  name = "${var.prefix_code}-tf-data"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket", "s3:DeleteBucket", "s3:ListBucket",
          "s3:GetBucketPolicy", "s3:PutBucketPolicy", "s3:DeleteBucketPolicy",
          "s3:GetBucketVersioning", "s3:PutBucketVersioning",
          "s3:GetEncryptionConfiguration", "s3:PutEncryptionConfiguration",
          "s3:GetBucketPublicAccessBlock", "s3:PutBucketPublicAccessBlock",
          "s3:GetBucketAcl", "s3:PutBucketAcl",
          "s3:GetBucketCORS", "s3:PutBucketCORS",
          "s3:GetBucketLogging", "s3:PutBucketLogging",
          "s3:GetBucketNotification", "s3:PutBucketNotification",
          "s3:GetBucketTagging", "s3:PutBucketTagging",
          "s3:GetBucketOwnershipControls", "s3:PutBucketOwnershipControls",
          "s3:GetLifecycleConfiguration", "s3:PutLifecycleConfiguration",
          "s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion",
          "s3:GetObjectVersion", "s3:ListBucketVersions",
          "s3:GetBucketLocation",
          "s3:GetAccelerateConfiguration", "s3:GetBucketRequestPayment",
          "s3:GetBucketWebsite", "s3:GetReplicationConfiguration",
          "s3:GetObjectTagging", "s3:PutObjectTagging",
          "s3:GetBucketObjectLockConfiguration"
        ]
        Resource = ["arn:aws:s3:::${local.prefix}-*", "arn:aws:s3:::${local.prefix}-*/*"]
      },
      {
        #checkov:skip=CKV_AWS_355:dynamodb:ListTables requires Resource=* (account-level API)
        Sid    = "DynamoDB"
        Effect = "Allow"
        Action = [
          "dynamodb:CreateTable", "dynamodb:DeleteTable", "dynamodb:DescribeTable",
          "dynamodb:UpdateTable", "dynamodb:DescribeContinuousBackups",
          "dynamodb:UpdateContinuousBackups", "dynamodb:DescribeTimeToLive",
          "dynamodb:UpdateTimeToLive", "dynamodb:ListTagsOfResource",
          "dynamodb:TagResource", "dynamodb:UntagResource",
          "dynamodb:ListTables"
        ]
        Resource = "*"
      },
      {
        Sid    = "S3Tables"
        Effect = "Allow"
        Action = [
          "s3tables:CreateTableBucket", "s3tables:DeleteTableBucket",
          "s3tables:GetTableBucket", "s3tables:GetTableBucketMaintenanceConfiguration",
          "s3tables:GetTableBucketEncryption", "s3tables:GetTableBucketPolicy",
          "s3tables:GetTableBucketStorageClass", "s3tables:GetTableBucketReplication",
          "s3tables:GetTableBucketMetricsConfiguration",
          "s3tables:PutTableBucketPolicy", "s3tables:DeleteTableBucketPolicy",
          "s3tables:CreateNamespace", "s3tables:DeleteNamespace", "s3tables:GetNamespace", "s3tables:ListNamespaces",
          "s3tables:ListTableBuckets", "s3tables:ListTables", "s3tables:DeleteTable",
          "s3tables:TagResource", "s3tables:UntagResource", "s3tables:ListTagsForResource"
        ]
        Resource = [
          "arn:aws:s3tables:${local.region}:${local.account_id}:bucket/${local.prefix}-*",
          "arn:aws:s3tables:${local.region}:${local.account_id}:bucket/${local.prefix}-*/table/*"
        ]
      },
      {
        Sid    = "Glue"
        Effect = "Allow"
        Action = [
          "glue:CreateDatabase", "glue:DeleteDatabase", "glue:GetDatabase", "glue:GetDatabases", "glue:UpdateDatabase",
          "glue:CreateTable", "glue:DeleteTable", "glue:GetTable", "glue:GetTables", "glue:UpdateTable",
          "glue:CreateJob", "glue:DeleteJob", "glue:GetJob", "glue:GetJobs", "glue:UpdateJob",
          "glue:CreateSecurityConfiguration", "glue:DeleteSecurityConfiguration", "glue:GetSecurityConfiguration",
          "glue:TagResource", "glue:UntagResource", "glue:GetTags"
        ]
        Resource = "*"
      },
      {
        Sid    = "Redshift"
        Effect = "Allow"
        Action = [
          "redshift-serverless:CreateNamespace", "redshift-serverless:DeleteNamespace",
          "redshift-serverless:GetNamespace", "redshift-serverless:UpdateNamespace",
          "redshift-serverless:CreateWorkgroup", "redshift-serverless:DeleteWorkgroup",
          "redshift-serverless:GetWorkgroup", "redshift-serverless:UpdateWorkgroup",
          "redshift-serverless:CreateUsageLimit", "redshift-serverless:DeleteUsageLimit",
          "redshift-serverless:GetUsageLimit", "redshift-serverless:ListUsageLimits",
          "redshift-serverless:GetCredentials",
          "redshift-serverless:TagResource", "redshift-serverless:UntagResource", "redshift-serverless:ListTagsForResource",
          "redshift-data:ExecuteStatement", "redshift-data:DescribeStatement", "redshift-data:GetStatementResult"
        ]
        Resource = "*"
      },
      {
        Sid    = "LakeFormation"
        Effect = "Allow"
        Action = [
          "lakeformation:GrantPermissions", "lakeformation:RevokePermissions",
          "lakeformation:GetDataAccess", "lakeformation:ListPermissions",
          "lakeformation:BatchGrantPermissions", "lakeformation:BatchRevokePermissions"
        ]
        Resource = "*"
      },
      {
        Sid    = "TFState"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket", "s3:GetBucketVersioning"]
        Resource = [
          "arn:aws:s3:::${local.prefix}-tfstate-${local.account_id}-${local.region}",
          "arn:aws:s3:::${local.prefix}-tfstate-${local.account_id}-${local.region}/*"
        ]
      }
    ]
  })
  tags = {
    Name         = "${local.prefix}-policy-tf-data"
    resourcetype = "security"
    codeblock    = "iam-policy"
  }

}

# Policy 4: Orchestration & AI (Step Functions, Scheduler, Bedrock, Cognito)

resource "aws_iam_policy" "tf_orchestration_ai" {
  #checkov:skip=CKV_AWS_355:Bedrock, bedrock-agentcore:CreateAgentRuntime/CreateGateway and cognito-idp:CreateUserPool/DescribeUserPoolDomain require Resource=* (https://docs.aws.amazon.com/service-authorization/latest/reference/reference_policies_actions-resources-contextkeys.html)
  #checkov:skip=CKV_AWS_290:CI/CD role needs write access to deploy infrastructure
  name = "${var.prefix_code}-tf-orchestration-ai"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "StepFunctions"
        Effect = "Allow"
        Action = [
          "states:CreateStateMachine", "states:DeleteStateMachine",
          "states:DescribeStateMachine", "states:UpdateStateMachine",
          "states:ListStateMachines",
          "states:ListStateMachineVersions",
          "states:TagResource", "states:UntagResource", "states:ListTagsForResource"
        ]
        Resource = "arn:aws:states:${local.region}:${local.account_id}:stateMachine:${local.prefix}-*"
      },
      {
        Sid      = "StepFunctionsValidate"
        Effect   = "Allow"
        Action   = ["states:ValidateStateMachineDefinition"]
        Resource = "arn:aws:states:${local.region}:${local.account_id}:stateMachine:*"
      },
      {
        Sid    = "Scheduler"
        Effect = "Allow"
        Action = [
          "scheduler:CreateSchedule", "scheduler:DeleteSchedule",
          "scheduler:GetSchedule", "scheduler:UpdateSchedule",
          "scheduler:ListSchedules",
          "scheduler:TagResource", "scheduler:UntagResource", "scheduler:ListTagsForResource"
        ]
        Resource = "arn:aws:scheduler:*:${local.account_id}:schedule/default/${local.prefix}-*"
      },
      {
        Sid    = "Bedrock"
        Effect = "Allow"
        Action = [
          "bedrock:CreateGuardrail", "bedrock:UpdateGuardrail",
          "bedrock:DeleteGuardrail", "bedrock:GetGuardrail",
          "bedrock:CreateGuardrailVersion", "bedrock:DeleteGuardrailVersion",
          "bedrock:GetGuardrailVersion", "bedrock:ListGuardrails",
          "bedrock:TagResource", "bedrock:UntagResource", "bedrock:ListTagsForResource"
        ]
        Resource = "*"
      },
      {
        # The runtimes, the gateway and its targets, and the workload identities AgentCore creates for them
        Sid    = "AgentCore"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetAgentRuntime",
          "bedrock-agentcore:UpdateAgentRuntime", "bedrock-agentcore:DeleteAgentRuntime",
          "bedrock-agentcore:CreateAgentRuntimeEndpoint", "bedrock-agentcore:GetAgentRuntimeEndpoint",
          "bedrock-agentcore:UpdateAgentRuntimeEndpoint", "bedrock-agentcore:DeleteAgentRuntimeEndpoint",
          "bedrock-agentcore:GetGateway",
          "bedrock-agentcore:UpdateGateway", "bedrock-agentcore:DeleteGateway",
          "bedrock-agentcore:CreateGatewayTarget", "bedrock-agentcore:GetGatewayTarget",
          "bedrock-agentcore:UpdateGatewayTarget", "bedrock-agentcore:DeleteGatewayTarget",
          "bedrock-agentcore:ListGatewayTargets",
          "bedrock-agentcore:CreateWorkloadIdentity", "bedrock-agentcore:GetWorkloadIdentity",
          "bedrock-agentcore:DeleteWorkloadIdentity",
          "bedrock-agentcore:AllowVendedLogDeliveryForResource",
          "bedrock-agentcore:TagResource", "bedrock-agentcore:UntagResource", "bedrock-agentcore:ListTagsForResource"
        ]
        Resource = "arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:*"
      },
      {
        # These actions have no resource type
        Sid      = "AgentCoreCreate"
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:CreateAgentRuntime", "bedrock-agentcore:CreateGateway"]
        Resource = "*"
      },
      {
        # These actions have no resource type
        Sid      = "CognitoAccountLevel"
        Effect   = "Allow"
        Action   = ["cognito-idp:CreateUserPool", "cognito-idp:DescribeUserPoolDomain"]
        Resource = "*"
      },
      {
        Sid    = "Cognito"
        Effect = "Allow"
        Action = [
          "cognito-idp:DeleteUserPool",
          "cognito-idp:DescribeUserPool", "cognito-idp:UpdateUserPool",
          "cognito-idp:GetUserPoolMfaConfig", "cognito-idp:SetUserPoolMfaConfig",
          "cognito-idp:CreateUserPoolClient", "cognito-idp:DeleteUserPoolClient",
          "cognito-idp:DescribeUserPoolClient", "cognito-idp:UpdateUserPoolClient",
          "cognito-idp:ListUserPoolClients",
          "cognito-idp:CreateUserPoolDomain", "cognito-idp:DeleteUserPoolDomain",
          "cognito-idp:UpdateUserPoolDomain",
          "cognito-idp:CreateManagedLoginBranding", "cognito-idp:DeleteManagedLoginBranding",
          "cognito-idp:DescribeManagedLoginBranding", "cognito-idp:DescribeManagedLoginBrandingByClient",
          "cognito-idp:UpdateManagedLoginBranding",
          "cognito-idp:TagResource", "cognito-idp:UntagResource",
          "cognito-idp:AdminCreateUser", "cognito-idp:AdminDeleteUser",
          "cognito-idp:AdminSetUserPassword", "cognito-idp:AdminGetUser"
        ]
        Resource = "arn:aws:cognito-idp:${local.region}:${local.account_id}:userpool/*"
      },
      {
        Sid    = "AutoScaling"
        Effect = "Allow"
        Action = [
          "application-autoscaling:RegisterScalableTarget", "application-autoscaling:DeregisterScalableTarget",
          "application-autoscaling:DescribeScalableTargets",
          "application-autoscaling:PutScalingPolicy", "application-autoscaling:DeleteScalingPolicy",
          "application-autoscaling:DescribeScalingPolicies",
          "application-autoscaling:DescribeScalingActivities",
          "application-autoscaling:ListTagsForResource",
          "application-autoscaling:TagResource", "application-autoscaling:UntagResource"
        ]
        Resource = "*"
      },
      {
        Sid    = "APIGateway"
        Effect = "Allow"
        Action = [
          "apigateway:GET", "apigateway:POST", "apigateway:PUT",
          "apigateway:PATCH", "apigateway:DELETE",
          "apigateway:TagResource", "apigateway:UntagResource"
        ]
        Resource = "arn:aws:apigateway:${local.region}::/*"
      }
    ]
  })
  tags = {
    Name         = "${local.prefix}-policy-tf-orchestration-ai"
    resourcetype = "security"
    codeblock    = "iam-policy"
  }

}

# Policy 5: Security & Observability (IAM, KMS, Secrets, SSM, CloudWatch, X-Ray)

resource "aws_iam_policy" "tf_security_obs" {
  #checkov:skip=CKV_AWS_355:kms:CreateKey, ssm:DescribeParameters, sts:GetCallerIdentity and the Logs, CloudTrail, X-Ray, Application Signals and resource group account-level calls have no resource-level permissions (https://docs.aws.amazon.com/service-authorization/latest/reference/reference_policies_actions-resources-contextkeys.html)
  #checkov:skip=CKV_AWS_290:CI/CD role needs write access to deploy infrastructure
  #checkov:skip=CKV_AWS_289:iam:CreateRole/AttachRolePolicy needed for Terraform-managed roles, scoped to prefix
  #checkov:skip=CKV_AWS_286:iam:CreateRole/PassRole needed for Terraform-managed service roles, scoped to prefix
  #checkov:skip=CKV2_AWS_40:CI/CD role manages IAM roles for all platform services, scoped to prefix
  #checkov:skip=CKV_AWS_288:CI/CD role reads Terraform state and config, scoped to prefix
  name = "${var.prefix_code}-tf-security-obs"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "IAMRoles"
        Effect = "Allow"
        Action = [
          "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:UpdateRole",
          "iam:UpdateAssumeRolePolicy",
          "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies",
          "iam:ListRolePolicies", "iam:ListInstanceProfilesForRole",
          "iam:TagRole", "iam:UntagRole", "iam:ListRoleTags",
          "iam:PassRole", "iam:CreateServiceLinkedRole"
        ]
        Resource = [
          "arn:aws:iam::${local.account_id}:role/${local.prefix}-*",
          "arn:aws:iam::${local.account_id}:role/aws-service-role/*"
        ]
      },
      {
        Sid    = "KMS"
        Effect = "Allow"
        Action = [
          "kms:CreateKey", "kms:DescribeKey", "kms:GetKeyPolicy", "kms:GetKeyRotationStatus",
          "kms:PutKeyPolicy", "kms:EnableKeyRotation", "kms:DisableKeyRotation",
          "kms:ScheduleKeyDeletion", "kms:CancelKeyDeletion",
          "kms:CreateAlias", "kms:DeleteAlias", "kms:UpdateAlias", "kms:ListAliases",
          "kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:ReEncryptFrom", "kms:ReEncryptTo",
          "kms:TagResource", "kms:UntagResource", "kms:ListResourceTags",
          "kms:CreateGrant", "kms:ListGrants", "kms:RevokeGrant"
        ]
        Resource = "*"
      },
      {
        Sid    = "SecretsManager"
        Effect = "Allow"
        Action = [
          "secretsmanager:CreateSecret", "secretsmanager:DeleteSecret",
          "secretsmanager:DescribeSecret", "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue", "secretsmanager:UpdateSecret",
          "secretsmanager:GetResourcePolicy", "secretsmanager:PutResourcePolicy", "secretsmanager:DeleteResourcePolicy",
          "secretsmanager:TagResource", "secretsmanager:UntagResource",
          "secretsmanager:RestoreSecret", "secretsmanager:UpdateSecretVersionStage"
        ]
        Resource = "arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:${local.prefix}-*"
      },
      {
        Sid    = "SSM"
        Effect = "Allow"
        Action = [
          "ssm:PutParameter", "ssm:GetParameter", "ssm:GetParameters",
          "ssm:GetParametersByPath",
          "ssm:DeleteParameter",
          "ssm:AddTagsToResource", "ssm:RemoveTagsFromResource", "ssm:ListTagsForResource"
        ]
        Resource = "arn:aws:ssm:${local.region}:${local.account_id}:parameter/${local.prefix}/*"
      },
      {
        Sid      = "SSMDescribe"
        Effect   = "Allow"
        Action   = ["ssm:DescribeParameters"]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:DescribeLogGroups",
          "logs:PutRetentionPolicy", "logs:DeleteRetentionPolicy",
          "logs:CreateLogStream", "logs:DeleteLogStream", "logs:DescribeLogStreams",
          "logs:PutLogEvents", "logs:FilterLogEvents",
          "logs:TagLogGroup", "logs:UntagLogGroup", "logs:TagResource", "logs:UntagResource",
          "logs:ListTagsForResource", "logs:ListTagsLogGroup",
          "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DeleteResourcePolicy",
          "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery", "logs:ListLogDeliveries",
          "logs:GetDeliveryDestination", "logs:PutDeliveryDestination", "logs:DeleteDeliveryDestination",
          "logs:GetDeliverySource", "logs:PutDeliverySource", "logs:DeleteDeliverySource",
          "logs:CreateDelivery", "logs:GetDelivery", "logs:DeleteDelivery",
          "logs:AssociateKmsKey", "logs:DisassociateKmsKey"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudTrail"
        Effect = "Allow"
        Action = [
          "cloudtrail:CreateTrail", "cloudtrail:UpdateTrail", "cloudtrail:DeleteTrail", "cloudtrail:DescribeTrails",
          "cloudtrail:GetTrailStatus", "cloudtrail:GetTrail",
          "cloudtrail:StartLogging", "cloudtrail:StopLogging",
          "cloudtrail:PutEventSelectors", "cloudtrail:GetEventSelectors",
          "cloudtrail:AddTags", "cloudtrail:RemoveTags", "cloudtrail:ListTags",
          "cloudtrail:GetInsightSelectors", "cloudtrail:PutInsightSelectors"
        ]
        Resource = "*"
      },
      {
        Sid      = "ApplicationSignals"
        Effect   = "Allow"
        Action   = ["application-signals:StartDiscovery"]
        Resource = "*"
      },
      {
        Sid      = "ApplicationSignalsChannel"
        Effect   = "Allow"
        Action   = ["cloudtrail:CreateServiceLinkedChannel"]
        Resource = "arn:aws:cloudtrail:*:${local.account_id}:channel/aws-service-channel/application-signals/*"
      },
      {
        Sid    = "XRay"
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments", "xray:PutTelemetryRecords",
          "xray:GetSamplingRules", "xray:GetSamplingTargets",
          "xray:PutEncryptionConfig", "xray:GetEncryptionConfig",
          "xray:PutResourcePolicy", "xray:ListResourcePolicies",
          # Transaction Search: Terraform sends traces to CloudWatch Logs
          "xray:GetTraceSegmentDestination", "xray:UpdateTraceSegmentDestination",
          "xray:GetIndexingRules", "xray:UpdateIndexingRule"
        ]
        Resource = "*"
      },
      {
        Sid    = "ResourceGroups"
        Effect = "Allow"
        Action = [
          "resource-groups:CreateGroup", "resource-groups:DeleteGroup",
          "resource-groups:GetGroup", "resource-groups:GetGroupQuery",
          "resource-groups:UpdateGroup", "resource-groups:UpdateGroupQuery",
          "resource-groups:GetGroupConfiguration",
          "resource-groups:Tag", "resource-groups:Untag", "resource-groups:GetTags",
          "tag:GetResources", "tag:TagResources", "tag:UntagResources"
        ]
        Resource = "*"
      },
      {
        Sid      = "STS"
        Effect   = "Allow"
        Action   = ["sts:GetCallerIdentity"]
        Resource = "*"
      }
    ]
  })
  tags = {
    Name         = "${local.prefix}-policy-tf-security-obs"
    resourcetype = "security"
    codeblock    = "iam-policy"
  }

}

