plugin "aws" {
  enabled = true
  version = "0.49.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}

# The terraform ruleset's recommended preset is on by default; this adds the steering's tag rule
rule "aws_resource_missing_tags" {
  enabled = true
  tags    = ["Name", "resourcetype", "codeblock"]
}
