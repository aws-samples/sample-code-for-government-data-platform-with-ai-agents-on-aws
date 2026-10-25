# DynamoDB table for shareable answer permalinks with 90-day TTL

resource "aws_dynamodb_table" "shared_answers" {
  name         = "${var.PrefixCode}-shared-answers"
  billing_mode = "PAY_PER_REQUEST"

  hash_key = "share_id"

  attribute {
    name = "share_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.datalake.arn
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name         = "${var.PrefixCode}-dynamodb-shared-answers"
    resourcetype = "database"
    codeblock    = "83-dynamodb-shared-answers"
  }
}
