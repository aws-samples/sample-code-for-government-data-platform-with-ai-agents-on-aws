# VPC with public and private subnets and a NAT gateway for Redshift and ECS

locals {
  vpc_cidr = "10.180.0.0/16"
  azs      = sort(data.aws_availability_zones.available.names)
}

resource "aws_vpc" "main" {
  cidr_block           = local.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name         = "${var.PrefixCode}-vpc"
    resourcetype = "network"
    codeblock    = "31-vpc"
  }
}

# Strip every rule from the default security group
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name         = "${var.PrefixCode}-sg-default-locked"
    resourcetype = "security"
    codeblock    = "31-vpc"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name         = "${var.PrefixCode}-igw"
    resourcetype = "network"
    codeblock    = "31-vpc"
  }
}

# Public subnets for the ALB and NAT gateway
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(local.vpc_cidr, 8, count.index + 1)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = false

  tags = {
    Name         = "${var.PrefixCode}-subnet-public-${count.index + 1}"
    resourcetype = "network"
    codeblock    = "31-vpc"
  }
}

# Private subnets for Redshift, ECS and the VPC endpoints
resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(local.vpc_cidr, 8, count.index + 10)
  availability_zone = local.azs[count.index]

  tags = {
    Name         = "${var.PrefixCode}-subnet-private-${count.index + 1}"
    resourcetype = "network"
    codeblock    = "31-vpc"
  }
}

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name         = "${var.PrefixCode}-eip-nat"
    resourcetype = "network"
    codeblock    = "31-vpc"
  }

  # The provider docs require the gateway to exist before the EIP and NAT; neither references it
  depends_on = [aws_internet_gateway.main]
}

# Outbound internet for the private subnets
resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id

  tags = {
    Name         = "${var.PrefixCode}-nat"
    resourcetype = "network"
    codeblock    = "31-vpc"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name         = "${var.PrefixCode}-rt-public"
    resourcetype = "network"
    codeblock    = "31-vpc"
  }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = {
    Name         = "${var.PrefixCode}-rt-private"
    resourcetype = "network"
    codeblock    = "31-vpc"
  }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# VPC Flow Logs
resource "aws_cloudwatch_log_group" "vpc_flow_logs" {
  name              = "/aws/vpc/${var.PrefixCode}-flowlogs"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.datalake.arn

  tags = {
    Name         = "${var.PrefixCode}-vpc-flowlogs"
    resourcetype = "monitoring"
    codeblock    = "31-vpc"
  }
}

resource "aws_iam_role" "vpc_flow_logs" {
  name = "${var.PrefixCode}-iamrole-vpcflowlogs"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "vpc-flow-logs.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.PrefixCode}-iamrole-vpcflowlogs"
    resourcetype = "security"
    codeblock    = "31-vpc"
  }
}

resource "aws_iam_role_policy" "vpc_flow_logs" {
  name = "${var.PrefixCode}-policy-vpcflowlogs"
  role = aws_iam_role.vpc_flow_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams"
      ]
      Resource = "${aws_cloudwatch_log_group.vpc_flow_logs.arn}:*"
    }]
  })
}

resource "aws_flow_log" "main" {
  vpc_id                   = aws_vpc.main.id
  traffic_type             = "ALL"
  log_destination_type     = "cloud-watch-logs"
  log_destination          = aws_cloudwatch_log_group.vpc_flow_logs.arn
  iam_role_arn             = aws_iam_role.vpc_flow_logs.arn
  max_aggregation_interval = 60

  tags = {
    Name         = "${var.PrefixCode}-flowlog"
    resourcetype = "monitoring"
    codeblock    = "31-vpc"
  }
}


# S3 VPC Endpoint - Private subnet access to S3
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.Region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = {
    Name         = "${var.PrefixCode}-vpce-s3"
    resourcetype = "network"
    codeblock    = "31-vpc"
  }
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.Region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = {
    Name         = "${var.PrefixCode}-vpce-dynamodb"
    resourcetype = "network"
    codeblock    = "31-vpc"
  }
}


