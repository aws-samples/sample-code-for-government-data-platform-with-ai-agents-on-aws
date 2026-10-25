# Platform settings read by the pipeline on every run
# PrefixCode and Region are overridden with -var from bootstrap, values here are for local reference

PrefixCode              = "govdata"
Region                  = "eu-west-2"
AvailabilityZones       = ["eu-west-2a", "eu-west-2b"]
BedrockModelSmart       = "eu.anthropic.claude-sonnet-4-6"
BedrockModelFast        = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
RedshiftWarmupEnabled   = false
BedrockGuardrailEnabled = true
