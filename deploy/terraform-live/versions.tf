# Provider versions, S3 backend and default tags
terraform {
  required_version = ">= 1.14.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.68.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.6.3"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "2.8.1"
    }
  }

  backend "s3" {
    # The pipeline passes bucket, key and region with -backend-config
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.Region

  default_tags {
    tags = {
      solution = "one-gov-data-platform"
    }
  }
}
