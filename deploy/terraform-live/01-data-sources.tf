# Data sources shared across the root: account, availability zones and the CloudFront origin prefix list
data "aws_caller_identity" "current" {}

# Pinned to the configured zones, which keeps the subnet placement fixed if AWS adds a zone to the region
data "aws_availability_zones" "available" {
  state = "available"

  filter {
    name   = "zone-name"
    values = var.AvailabilityZones
  }
}

# CloudFront's origin-facing ranges, the only ingress the webapp ALB accepts
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}
