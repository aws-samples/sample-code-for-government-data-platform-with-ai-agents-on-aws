# Dashboard: GOV.UK kiosk display on ECS Fargate, shares ALB/VPC with webapp

# ECR repository
resource "aws_ecr_repository" "dashboard" {
  name                 = "${var.PrefixCode}/dashboard"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.datalake.arn
  }

  tags = {
    Name         = "${var.PrefixCode}-ecr-dashboard"
    resourcetype = "compute"
    codeblock    = "87-ecs-dashboard"
  }
}

# SSM parameter for image tag (written by CodeBuild)
resource "aws_ssm_parameter" "dashboard_image_tag" {
  name   = "/${var.PrefixCode}/dashboard-image-tag"
  type   = "SecureString"
  key_id = aws_kms_key.datalake.arn
  value  = "initial"

  lifecycle { ignore_changes = [value] }

  tags = {
    Name         = "${var.PrefixCode}-ssm-dashboard-image-tag"
    resourcetype = "config"
    codeblock    = "87-ecs-dashboard"
  }
}

# Security group for dashboard tasks (same pattern as webapp)
resource "aws_security_group" "dashboard" {
  #checkov:skip=CKV_AWS_382:Dashboard ECS tasks require egress for ECR pulls, CloudWatch, and API calls, https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html
  name        = "${var.PrefixCode}-sg-dashboard"
  description = "Dashboard ECS Fargate service"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Allow ALB to dashboard"
    from_port       = 3001
    to_port         = 3001
    protocol        = "tcp"
    security_groups = [aws_security_group.webapp_alb.id]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name         = "${var.PrefixCode}-sg-dashboard"
    resourcetype = "network"
    codeblock    = "87-ecs-dashboard"
  }
}

# Target group
resource "aws_lb_target_group" "dashboard" {
  #checkov:skip=CKV_AWS_378:Internal ALB-to-ECS traffic in private subnet, HTTPS terminates at CloudFront, https://docs.aws.amazon.com/elasticloadbalancing/latest/application/create-https-listener.html
  name                 = "${var.PrefixCode}-tg-dashboard"
  port                 = 3001
  protocol             = "HTTP"
  vpc_id               = aws_vpc.main.id
  target_type          = "ip"
  deregistration_delay = 30

  health_check {
    enabled             = true
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    path                = "/health"
    matcher             = "200"
    port                = "traffic-port"
    protocol            = "HTTP"
  }

  tags = {
    Name         = "${var.PrefixCode}-tg-dashboard"
    resourcetype = "network"
    codeblock    = "87-ecs-dashboard"
  }
}

# Listener rule: /dashboard* with the CloudFront header
resource "aws_lb_listener_rule" "dashboard" {
  listener_arn = aws_lb_listener.webapp.arn
  priority     = 5

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.dashboard.arn
  }

  condition {
    path_pattern { values = ["/dashboard", "/dashboard/*"] }
  }

  condition {
    http_header {
      http_header_name = local.cf_header_name
      values           = [local.cf_header_value]
    }
  }

  tags = {
    Name         = "${var.PrefixCode}-listener-rule-dashboard"
    resourcetype = "network"
    codeblock    = "87-ecs-dashboard"
  }
}

# Task role: signs GET /metrics with SigV4
resource "aws_iam_role" "dashboard_task" {
  name = "${var.PrefixCode}-iamrole-dashboard-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.PrefixCode}-iamrole-dashboard-task"
    resourcetype = "security"
    codeblock    = "87-ecs-dashboard"
  }
}

resource "aws_iam_role_policy" "dashboard_task_metrics" {
  name = "${var.PrefixCode}-policy-dashboard-task-metrics"
  role = aws_iam_role.dashboard_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["execute-api:Invoke"]
        Resource = "${aws_apigatewayv2_api.dashboard.execution_arn}/*/GET/metrics"
      },
      {
        # The Cognito pool and client ids the sign-in check verifies tokens against
        Sid      = "CognitoVerify"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = aws_ssm_parameter.cognito_verify.arn
      },
      {
        # Decrypts the cognito-verify parameter, through SSM only
        Sid      = "CognitoVerifyDecrypt"
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = aws_kms_key.datalake.arn
        Condition = {
          StringEquals = { "kms:ViaService" = "ssm.${var.Region}.amazonaws.com" }
        }
      }
    ]
  })
}

# Task definition
resource "aws_ecs_task_definition" "dashboard" {
  #checkov:skip=CKV_AWS_336:Dashboard writes temp files (Nunjucks cache), read-only root filesystem breaks the app
  family                   = "${var.PrefixCode}-dashboard-task"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.dashboard_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name         = "${var.PrefixCode}-dashboard"
    image        = "${aws_ecr_repository.dashboard.repository_url}:${aws_ssm_parameter.dashboard_image_tag.value}"
    essential    = true
    portMappings = [{ containerPort = 3001, protocol = "tcp" }]
    environment = [
      { name = "PORT", value = "3001" },
      { name = "DASHBOARD_API_URL", value = "${aws_apigatewayv2_api.dashboard.api_endpoint}/metrics" },
      { name = "DASHBOARD_API_REGION", value = var.Region },
      { name = "COGNITO_CONFIG_PARAM", value = aws_ssm_parameter.cognito_verify.name },
      { name = "APP_BASE_URL", value = "https://${aws_cloudfront_distribution.webapp.domain_name}" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.dashboard.name
        "awslogs-region"        = var.Region
        "awslogs-stream-prefix" = "dashboard"
      }
    }
  }])

  tags = {
    Name         = "${var.PrefixCode}-dashboard-task"
    resourcetype = "compute"
    codeblock    = "87-ecs-dashboard"
  }
}

resource "aws_cloudwatch_log_group" "dashboard" {
  name              = "/aws/ecs/${var.PrefixCode}-dashboard"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.datalake.arn

  tags = {
    Name         = "${var.PrefixCode}-logs-dashboard"
    resourcetype = "monitoring"
    codeblock    = "87-ecs-dashboard"
  }
}

# ECS service
resource "aws_ecs_service" "dashboard" {
  name            = "${var.PrefixCode}-dashboard-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.dashboard.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.dashboard.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.dashboard.arn
    container_name   = "${var.PrefixCode}-dashboard"
    container_port   = 3001
  }

  # ECS rejects a service whose target group isn't attached to a listener; the rule is what attaches it
  depends_on = [aws_lb_listener_rule.dashboard]

  tags = {
    Name         = "${var.PrefixCode}-dashboard-service"
    resourcetype = "compute"
    codeblock    = "87-ecs-dashboard"
  }
}
