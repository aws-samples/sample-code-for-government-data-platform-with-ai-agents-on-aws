# S3 Tables: managed Iceberg table buckets for silver and gold

# Glue creates and writes tables; Spectrum only reads
locals {
  s3tables_read_actions = [
    "s3tables:GetTable", "s3tables:GetTableBucket", "s3tables:GetTableData", "s3tables:GetTableMetadataLocation",
    "s3tables:ListTables", "s3tables:GetNamespace", "s3tables:ListNamespaces"
  ]
  s3tables_write_actions = concat(local.s3tables_read_actions, [
    "s3tables:PutTableData", "s3tables:UpdateTableMetadataLocation", "s3tables:CreateTable"
  ])
}

resource "aws_s3tables_table_bucket" "gold" {
  name = "${var.PrefixCode}-datalake-gold-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name         = "${var.PrefixCode}-datalake-gold-${data.aws_caller_identity.current.account_id}"
    resourcetype = "analytics"
    codeblock    = "51-s3-tables"
  }
}

resource "aws_s3tables_namespace" "gold" {
  namespace        = "gold"
  table_bucket_arn = aws_s3tables_table_bucket.gold.arn
}

resource "aws_s3tables_table_bucket_policy" "gold" {
  table_bucket_arn = aws_s3tables_table_bucket.gold.arn
  resource_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowGlueWrite"
        Effect    = "Allow"
        Principal = { AWS = aws_iam_role.glue_etl.arn }
        Action    = local.s3tables_write_actions
        Resource = [
          aws_s3tables_table_bucket.gold.arn,
          "${aws_s3tables_table_bucket.gold.arn}/*"
        ]
      },
      {
        Sid       = "AllowRedshiftRead"
        Effect    = "Allow"
        Principal = { AWS = aws_iam_role.redshift_spectrum.arn }
        Action    = local.s3tables_read_actions
        Resource = [
          aws_s3tables_table_bucket.gold.arn,
          "${aws_s3tables_table_bucket.gold.arn}/*"
        ]
      }
    ]
  })
}

# Spectrum reads S3 Tables through Lake Formation credential vending, which needs these grants whatever IAM allows. The apply role must be a Lake Formation admin to make them
resource "aws_lakeformation_permissions" "spectrum_resource_link" {
  principal   = aws_iam_role.redshift_spectrum.arn
  permissions = ["DESCRIBE"]

  database {
    catalog_id = data.aws_caller_identity.current.account_id
    name       = aws_glue_catalog_database.gold_s3tables_link.name
  }
}

# Wildcard covers tables added later
resource "aws_lakeformation_permissions" "spectrum_gold_tables" {
  principal   = aws_iam_role.redshift_spectrum.arn
  permissions = ["SELECT", "DESCRIBE"]

  table {
    catalog_id    = "${data.aws_caller_identity.current.account_id}:s3tablescatalog/${aws_s3tables_table_bucket.gold.name}"
    database_name = aws_s3tables_namespace.gold.namespace
    wildcard      = true
  }
}

# Glue resource link that Redshift's external schema points at
resource "aws_glue_catalog_database" "gold_s3tables_link" {
  name = "${var.PrefixCode}_gold_s3tables"

  target_database {
    catalog_id    = "${data.aws_caller_identity.current.account_id}:s3tablescatalog/${aws_s3tables_table_bucket.gold.name}"
    database_name = aws_s3tables_namespace.gold.namespace
  }

  tags = {
    Name         = "${var.PrefixCode}-gluedb-gold-s3tables-link"
    resourcetype = "analytics"
    codeblock    = "51-s3-tables"
  }
  # Glue rewrites the link after creation and rejects UpdateDatabase on it, so nothing here can change in place (tags included)
  lifecycle {
    ignore_changes = all
  }
}

resource "aws_s3tables_table_bucket" "silver" {
  name = "${var.PrefixCode}-datalake-silver-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name         = "${var.PrefixCode}-datalake-silver-${data.aws_caller_identity.current.account_id}"
    resourcetype = "analytics"
    codeblock    = "51-s3-tables"
  }
}

resource "aws_s3tables_namespace" "silver" {
  namespace        = "silver"
  table_bucket_arn = aws_s3tables_table_bucket.silver.arn
}

resource "aws_s3tables_table_bucket_policy" "silver" {
  table_bucket_arn = aws_s3tables_table_bucket.silver.arn
  resource_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowGlueAccess"
        Effect = "Allow"
        Principal = {
          AWS = [aws_iam_role.glue_etl.arn]
        }
        Action = local.s3tables_write_actions
        Resource = [
          aws_s3tables_table_bucket.silver.arn,
          "${aws_s3tables_table_bucket.silver.arn}/*"
        ]
      }
    ]
  })
}
