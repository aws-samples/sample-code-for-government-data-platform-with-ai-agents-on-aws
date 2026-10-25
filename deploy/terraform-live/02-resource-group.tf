# Resource group to see all platform resources in one place in the console
resource "aws_resourcegroups_group" "platform" {
  name        = "${var.PrefixCode}-resourcegroup-platform"
  description = "All resources for the ${var.PrefixCode} data platform"

  resource_query {
    query = jsonencode({
      ResourceTypeFilters = ["AWS::AllSupported"]
      TagFilters = [{
        Key    = "solution"
        Values = ["one-gov-data-platform"]
      }]
    })
    type = "TAG_FILTERS_1_0"
  }

  tags = {
    Name         = "${var.PrefixCode}-resourcegroup-platform"
    resourcetype = "management"
    codeblock    = "02-resource-group"
  }
}
