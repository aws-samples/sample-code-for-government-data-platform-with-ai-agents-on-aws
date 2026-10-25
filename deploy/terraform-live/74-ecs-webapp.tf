# GOV.UK web application on ECS Fargate, the public frontend for the agents

# ECR repository for webapp container
resource "aws_ecr_repository" "webapp" {
  name                 = "${var.PrefixCode}/webapp"
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
    Name         = "${var.PrefixCode}-ecr-webapp"
    resourcetype = "compute"
    codeblock    = "74-ecs-webapp"
  }
}

# Image tag written by CodeBuild after each push and read here for the task definition
resource "aws_ssm_parameter" "webapp_image_tag" {
  name   = "/${var.PrefixCode}/webapp-image-tag"
  type   = "SecureString"
  key_id = aws_kms_key.datalake.arn
  value  = "initial"

  lifecycle { ignore_changes = [value] }

  tags = {
    Name         = "${var.PrefixCode}-ssm-webapp-image-tag"
    resourcetype = "config"
    codeblock    = "74-ecs-webapp"
  }
}

# CloudWatch log group for webapp
resource "aws_cloudwatch_log_group" "webapp" {
  name              = "/aws/ecs/${var.PrefixCode}-webapp"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.datalake.arn

  tags = {
    Name         = "${var.PrefixCode}-logs-webapp"
    resourcetype = "monitoring"
    codeblock    = "74-ecs-webapp"
  }
}

# Security group for public ALB - CloudFront only
resource "aws_security_group" "webapp_alb" {
  #checkov:skip=CKV_AWS_382:ALB requires egress to ECS tasks in private subnets for health checks, https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-security-groups.html
  name        = "${var.PrefixCode}-sg-webapp-alb"
  description = "Public ALB for GOV.UK webapp"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Allow HTTP from CloudFront only"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name         = "${var.PrefixCode}-sg-webapp-alb"
    resourcetype = "network"
    codeblock    = "74-ecs-webapp"
  }
}

# Security group for webapp Fargate tasks
resource "aws_security_group" "webapp" {
  #checkov:skip=CKV_AWS_382:ECS tasks require egress for ECR image pulls, CloudWatch, SSM, and Bedrock API calls, https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html
  name        = "${var.PrefixCode}-sg-webapp"
  description = "GOV.UK webapp ECS Fargate service"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Allow ALB to webapp"
    from_port       = 3000
    to_port         = 3000
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
    Name         = "${var.PrefixCode}-sg-webapp"
    resourcetype = "network"
    codeblock    = "74-ecs-webapp"
  }
}

# Public ALB for webapp
resource "aws_lb" "webapp" {
  #checkov:skip=CKV_AWS_91:No ALB access log; the webapp logs each request to CloudWatch and the ALB only accepts CloudFront traffic
  #checkov:skip=CKV2_AWS_28:Only CloudFront can reach the ALB (prefix list and secret header), no WAF
  #checkov:skip=CKV2_AWS_20:CloudFront redirects viewers to HTTPS; the ALB is an HTTP-only origin
  #checkov:skip=CKV_AWS_150:The teardown pipeline destroys the ALB, deletion protection would block it
  name               = "${var.PrefixCode}-alb-webapp"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.webapp_alb.id]
  subnets            = aws_subnet.public[*].id

  enable_deletion_protection = false
  drop_invalid_header_fields = true
  idle_timeout               = 300

  tags = {
    Name         = "${var.PrefixCode}-alb-webapp"
    resourcetype = "network"
    codeblock    = "74-ecs-webapp"
  }
}

# Target group for webapp containers
resource "aws_lb_target_group" "webapp" {
  #checkov:skip=CKV_AWS_378:Internal ALB-to-ECS traffic in private subnet, HTTPS terminates at CloudFront, https://docs.aws.amazon.com/elasticloadbalancing/latest/application/create-https-listener.html
  name                 = "${var.PrefixCode}-tg-webapp"
  port                 = 3000
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
    Name         = "${var.PrefixCode}-tg-webapp"
    resourcetype = "network"
    codeblock    = "74-ecs-webapp"
  }
}

# HTTP listener: 403 by default, the rule below forwards only CloudFront traffic
# nosemgrep: insecure-load-balancer-tls-version, TLS terminated at CloudFront, ALB is HTTP-only private origin
resource "aws_lb_listener" "webapp" {
  #checkov:skip=CKV_AWS_2:TLS terminated at CloudFront, ALB is HTTP-only origin behind secret header verification
  #checkov:skip=CKV_AWS_103:TLS terminated at CloudFront, ALB listener is intentionally HTTP
  load_balancer_arn = aws_lb.webapp.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Access Denied"
      status_code  = "403"
    }
  }

  tags = {
    Name         = "${var.PrefixCode}-listener-webapp"
    resourcetype = "network"
    codeblock    = "74-ecs-webapp"
  }
}

# Forward only when CloudFront origin verification header is present
resource "aws_lb_listener_rule" "webapp_cloudfront" {
  listener_arn = aws_lb_listener.webapp.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.webapp.arn
  }

  condition {
    http_header {
      http_header_name = local.cf_header_name
      values           = [local.cf_header_value]
    }
  }

  tags = {
    Name         = "${var.PrefixCode}-listener-rule-webapp-cf"
    resourcetype = "network"
    codeblock    = "74-ecs-webapp"
  }
}

# ECS task definition for webapp
resource "aws_ecs_task_definition" "webapp" {
  #checkov:skip=CKV_AWS_336:GOV.UK webapp writes temp files (Nunjucks cache, session data), read-only root filesystem breaks the app
  family                   = "${var.PrefixCode}-webapp-task"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.webapp_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name      = "${var.PrefixCode}-webapp"
      image     = "${aws_ecr_repository.webapp.repository_url}:${aws_ssm_parameter.webapp_image_tag.value}"
      essential = true

      portMappings = [{
        containerPort = 3000
        protocol      = "tcp"
      }]

      environment = [
        { name = "AGENT_RUNTIME_ARN_PARAM", value = "/${var.PrefixCode}/agent-runtime-arn" },
        { name = "WALKTHROUGH_RUNTIME_ARN_PARAM", value = "/${var.PrefixCode}/walkthrough-runtime-arn" },
        { name = "GEOSPATIAL_RUNTIME_ARN_PARAM", value = "/${var.PrefixCode}/geospatial-runtime-arn" },
        { name = "AWS_DEFAULT_REGION", value = var.Region },
        { name = "DATALAKE_BUCKET", value = module.datalake.bucket_id },
        { name = "DATA_SOURCE_REGISTRY_TABLE", value = aws_dynamodb_table.data_source_registry.name },
        { name = "DATASET_TRACKING_TABLE", value = aws_dynamodb_table.dataset_tracking.name },
        { name = "REDSHIFT_WORKGROUP", value = aws_redshiftserverless_workgroup.main.workgroup_name },
        { name = "BEDROCK_MODEL_ID", value = var.BedrockModelSmart },
        { name = "SHARED_ANSWERS_TABLE", value = aws_dynamodb_table.shared_answers.name },
        { name = "DASHBOARD_LIVE_TABLE", value = aws_dynamodb_table.dashboard_live.name },
        { name = "AGENTCORE_LOG_GROUP", value = module.agentcore_agent.vended_log_group_name },
        { name = "WALKTHROUGH_LOG_GROUP", value = module.agentcore_walkthrough.vended_log_group_name },
        { name = "GEOSPATIAL_LOG_GROUP", value = module.agentcore_geospatial.vended_log_group_name },
        { name = "COGNITO_CONFIG_PARAM", value = aws_ssm_parameter.cognito_config.name },
        { name = "APP_BASE_URL", value = "https://${aws_cloudfront_distribution.webapp.domain_name}" },
        { name = "PORT", value = "3000" },
        { name = "OTEL_RESOURCE_ATTRIBUTES", value = "service.name=${var.PrefixCode}-webapp" },
        { name = "OTEL_PROPAGATORS", value = "none" },
        { name = "OTEL_METRICS_EXPORTER", value = "none" },
      ]

      secrets = [
        { name = "COOKIE_SECRET", valueFrom = aws_secretsmanager_secret.webapp_cookie_secret.arn },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.webapp.name
          "awslogs-region"        = var.Region
          "awslogs-stream-prefix" = "webapp"
        }
      }

      readonlyRootFilesystem = false
    },
    {
      name      = "aws-otel-collector"
      image     = "public.ecr.aws/aws-observability/aws-otel-collector:v0.46.0"
      essential = false

      command = ["--config=/etc/ecs/ecs-xray.yaml"]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.webapp.name
          "awslogs-region"        = var.Region
          "awslogs-stream-prefix" = "otel"
        }
      }
    }
  ])

  tags = {
    Name         = "${var.PrefixCode}-webapp-task"
    resourcetype = "compute"
    codeblock    = "74-ecs-webapp"
  }
}

# ECS Fargate service for webapp
resource "aws_ecs_service" "webapp" {
  name            = "${var.PrefixCode}-webapp-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.webapp.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  enable_execute_command = true

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.webapp.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.webapp.arn
    container_name   = "${var.PrefixCode}-webapp"
    container_port   = 3000
  }

  # ECS rejects a service whose target group isn't attached to a listener; the rule is what attaches it
  depends_on = [aws_lb_listener_rule.webapp_cloudfront]

  # Autoscaling owns the count after the first apply
  lifecycle {
    ignore_changes = [desired_count]
  }

  tags = {
    Name         = "${var.PrefixCode}-webapp-service"
    resourcetype = "compute"
    codeblock    = "74-ecs-webapp"
  }
}

# Auto-scaling: CPU target tracking at 70%, 2-10 tasks
resource "aws_appautoscaling_target" "webapp" {
  max_capacity       = 10
  min_capacity       = 2
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.webapp.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
  tags = {
    Name         = "${var.PrefixCode}-autoscaling-webapp"
    resourcetype = "compute"
    codeblock    = "74-ecs-webapp"
  }
}

resource "aws_appautoscaling_policy" "webapp_cpu" {
  name               = "${var.PrefixCode}-webapp-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.webapp.resource_id
  scalable_dimension = aws_appautoscaling_target.webapp.scalable_dimension
  service_namespace  = aws_appautoscaling_target.webapp.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# Outputs
output "webapp_url" {
  value       = "https://${aws_cloudfront_distribution.webapp.domain_name}"
  description = "Public URL for the GOV.UK web application (via CloudFront)"
}
