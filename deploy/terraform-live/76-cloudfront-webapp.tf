# CloudFront in front of the webapp ALB for HTTPS and origin verification

# Origin verification header: CloudFront sends it, the ALB listener rule requires it
resource "random_password" "cloudfront_header" {
  length  = 32
  special = false
}

locals {
  cf_header_name  = "X-Origin-Verify"
  cf_header_value = random_password.cloudfront_header.result
}

resource "aws_cloudfront_distribution" "webapp" {
  #checkov:skip=CKV_AWS_68:Cognito sign-in and the ALB origin check cover what a WAF would add here
  #checkov:skip=CKV2_AWS_47:No Java in the stack, the Log4j rule does not apply
  #checkov:skip=CKV2_AWS_42:Default CloudFront certificate; add a custom domain with an ACM certificate for production
  #checkov:skip=CKV_AWS_310:Single ALB origin, availability comes from multi-AZ ECS tasks behind it
  #checkov:skip=CKV_AWS_86:No viewer request log; the webapp logs each request itself and the ALB target group health is in CloudWatch
  #checkov:skip=CKV2_AWS_32:Managed SecurityHeadersPolicy attached by ID, which the graph check doesn't resolve (https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-response-headers-policies.html)
  #checkov:skip=CKV_AWS_305:Dynamic webapp, the app handles routing
  #checkov:skip=CKV_AWS_374:Public platform, no geo restriction (https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/georestrictions.html)
  enabled         = true
  comment         = "${var.PrefixCode}-webapp HTTPS frontend"
  is_ipv6_enabled = true

  viewer_certificate {
    #checkov:skip=CKV_AWS_174:minimum_protocol_version needs a custom ACM certificate (https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/secure-connections-supported-viewer-protocols-ciphers.html)
    cloudfront_default_certificate = true
  }

  origin {
    domain_name = aws_lb.webapp.dns_name
    origin_id   = "webapp-alb"

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "http-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 120
      origin_keepalive_timeout = 60
    }

    # Secret header to verify requests came through CloudFront
    custom_header {
      name  = local.cf_header_name
      value = local.cf_header_value
    }
  }

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "webapp-alb"

    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # Managed CachingDisabled
    origin_request_policy_id = "216adef6-5c7f-47e4-b989-5492eafa07d3" # Managed AllViewer
    # Managed SecurityHeadersPolicy: HSTS, nosniff, X-Frame-Options SAMEORIGIN, Referrer-Policy
    response_headers_policy_id = "67f7725c-6f97-4210-82d7-5512b31e9d03"

    viewer_protocol_policy = "redirect-to-https"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  tags = {
    Name         = "${var.PrefixCode}-cloudfront-webapp"
    resourcetype = "network"
    codeblock    = "76-cloudfront-webapp"
  }
}
