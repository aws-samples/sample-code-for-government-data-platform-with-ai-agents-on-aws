# ECS Fargate cluster shared by the webapp and dashboard services, and the VPC endpoints their tasks use

resource "aws_ecs_cluster" "main" {
  #checkov:skip=CKV_AWS_65:The check only accepts "enabled"; "enhanced" is the newer Container Insights mode
  name = "${var.PrefixCode}-ecs-platform"

  setting {
    name  = "containerInsights"
    value = "enhanced"
  }

  tags = {
    Name         = "${var.PrefixCode}-ecs-platform"
    resourcetype = "compute"
    codeblock    = "70-ecs"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE"
  }
}

# Shared ECS execution role (ECR pull, CloudWatch logs) for the webapp and dashboard task definitions
resource "aws_iam_role" "ecs_execution" {
  name = "${var.PrefixCode}-iamrole-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.PrefixCode}-iamrole-ecs-execution"
    resourcetype = "security"
    codeblock    = "70-ecs"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "${var.PrefixCode}-policy-ecs-execution-secrets"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [aws_secretsmanager_secret.webapp_cookie_secret.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = aws_kms_key.datalake.arn
    }]
  })
}

# VPC endpoints for ECR image pulls and CloudWatch logs, keeping them off the NAT gateway
resource "aws_security_group" "vpce" {
  name        = "${var.PrefixCode}-sg-vpce"
  description = "VPC endpoints for ECS"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS from private subnets"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [for s in aws_subnet.private : s.cidr_block]
  }

  tags = {
    Name         = "${var.PrefixCode}-sg-vpce"
    resourcetype = "network"
    codeblock    = "70-ecs"
  }
}

resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.Region}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = {
    Name         = "${var.PrefixCode}-vpce-ecr-api"
    resourcetype = "network"
    codeblock    = "70-ecs"
  }
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.Region}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = {
    Name         = "${var.PrefixCode}-vpce-ecr-dkr"
    resourcetype = "network"
    codeblock    = "70-ecs"
  }
}

resource "aws_vpc_endpoint" "logs" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.Region}.logs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = {
    Name         = "${var.PrefixCode}-vpce-logs"
    resourcetype = "network"
    codeblock    = "70-ecs"
  }
}

resource "aws_vpc_endpoint" "ssmmessages" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.Region}.ssmmessages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = {
    Name         = "${var.PrefixCode}-vpce-ssmmessages"
    resourcetype = "network"
    codeblock    = "70-ecs"
  }
}

# The AWS APIs the data and walkthrough agents and the gateway tool Lambdas call, which have no route to the internet
resource "aws_vpc_endpoint" "agent_apis" {
  for_each            = toset(["bedrock-runtime", "redshift-data", "xray"])
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.Region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = {
    Name         = "${var.PrefixCode}-vpce-${each.key}"
    resourcetype = "network"
    codeblock    = "70-ecs"
  }
}

# AgentCore endpoint: the webapp calls InvokeAgentRuntime over PrivateLink
resource "aws_vpc_endpoint" "agentcore" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.Region}.bedrock-agentcore"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = {
    Name         = "${var.PrefixCode}-vpce-agentcore"
    resourcetype = "network"
    codeblock    = "70-ecs"
  }
}
