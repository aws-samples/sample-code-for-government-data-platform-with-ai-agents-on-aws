# DynamoDB table for tracking which datasets the agent queries per session

resource "aws_dynamodb_table" "dataset_tracking" {
  name         = "${var.PrefixCode}-dataset-tracking"
  billing_mode = "PAY_PER_REQUEST"

  hash_key  = "query_id"
  range_key = "table_name"

  attribute {
    name = "query_id"
    type = "S"
  }

  attribute {
    name = "table_name"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
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
    Name         = "${var.PrefixCode}-dynamodb-dataset-tracking"
    resourcetype = "database"
    codeblock    = "81-dynamodb-dataset-tracking"
  }
}
