# Data source registry, written by the gold Glue job

resource "aws_dynamodb_table" "data_source_registry" {
  name         = "${var.PrefixCode}-data-source-registry"
  billing_mode = "PAY_PER_REQUEST"

  hash_key = "source_id"

  attribute {
    name = "source_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.datalake.arn
  }

  tags = {
    Name         = "${var.PrefixCode}-dynamodb-data-source-registry"
    resourcetype = "database"
    codeblock    = "82-dynamodb-data-source-registry"
  }
}
