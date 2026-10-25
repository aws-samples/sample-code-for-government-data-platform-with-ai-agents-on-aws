# Bedrock Guardrails (content filtering, PII, profanity) enforced on the data and geospatial agents.

# Image filtering for Misconduct and Prompt Attack is GA only in these regions; elsewhere those two filters are text-only
locals {
  guardrail_full_image_regions = ["us-east-1", "us-west-2", "eu-central-1", "ap-northeast-1"]
  guardrail_extra_modalities   = contains(local.guardrail_full_image_regions, var.Region) ? ["TEXT", "IMAGE"] : ["TEXT"]
}

resource "aws_bedrock_guardrail" "agent" {
  name                      = "${var.PrefixCode}-guardrail-agent"
  description               = "Content safety guardrail for the Government Data Platform data agent"
  blocked_input_messaging   = "Sorry, I can't help you with that. [Input blocked by Bedrock Guardrail]"
  blocked_outputs_messaging = "Sorry, I can't help you with that. [Output blocked by Bedrock Guardrail]"
  kms_key_arn               = aws_kms_key.datalake.arn

  # Content filters: HATE, INSULTS, SEXUAL, MISCONDUCT and PROMPT_ATTACK at HIGH, VIOLENCE at MEDIUM; image modality where the region supports it
  content_policy_config {
    filters_config {
      type              = "HATE"
      input_strength    = "HIGH"
      output_strength   = "HIGH"
      input_action      = "BLOCK"
      output_action     = "BLOCK"
      input_enabled     = true
      output_enabled    = true
      input_modalities  = ["TEXT", "IMAGE"]
      output_modalities = ["TEXT", "IMAGE"]
    }
    filters_config {
      type              = "INSULTS"
      input_strength    = "HIGH"
      output_strength   = "HIGH"
      input_action      = "BLOCK"
      output_action     = "BLOCK"
      input_enabled     = true
      output_enabled    = true
      input_modalities  = ["TEXT", "IMAGE"]
      output_modalities = ["TEXT", "IMAGE"]
    }
    filters_config {
      type              = "SEXUAL"
      input_strength    = "HIGH"
      output_strength   = "HIGH"
      input_action      = "BLOCK"
      output_action     = "BLOCK"
      input_enabled     = true
      output_enabled    = true
      input_modalities  = ["TEXT", "IMAGE"]
      output_modalities = ["TEXT", "IMAGE"]
    }
    filters_config {
      type              = "VIOLENCE"
      input_strength    = "MEDIUM"
      output_strength   = "MEDIUM"
      input_action      = "BLOCK"
      output_action     = "BLOCK"
      input_enabled     = true
      output_enabled    = true
      input_modalities  = ["TEXT", "IMAGE"]
      output_modalities = ["TEXT", "IMAGE"]
    }
    filters_config {
      type              = "MISCONDUCT"
      input_strength    = "HIGH"
      output_strength   = "HIGH"
      input_action      = "BLOCK"
      output_action     = "BLOCK"
      input_enabled     = true
      output_enabled    = true
      input_modalities  = local.guardrail_extra_modalities
      output_modalities = local.guardrail_extra_modalities
    }
    filters_config {
      type             = "PROMPT_ATTACK"
      input_strength   = "HIGH"
      output_strength  = "NONE"
      input_action     = "BLOCK"
      input_enabled    = true
      input_modalities = local.guardrail_extra_modalities
    }
    tier_config {
      # CLASSIC tier: STANDARD needs cross_region_config, which the provider did not support when this was written (6.68.0)
      tier_name = "CLASSIC"
    }
  }

  # Denied topics, scoped narrowly to leave data questions alone
  topic_policy_config {
    topics_config {
      name       = "personal_advice"
      type       = "DENY"
      definition = "Personal medical, legal, or financial advice. Excludes public statistics about health, housing, employment, or crime."
      examples = [
        "Should I invest my savings in property?",
        "What medication should I take?",
        "Can you represent me in court?",
      ]
    }
  }

  # AWS credentials BLOCK, EMAIL/PHONE ANONYMIZE; NAME/ADDRESS omitted because the guardrail can't tell place names from personal PII
  sensitive_information_policy_config {
    pii_entities_config {
      type           = "AWS_ACCESS_KEY"
      action         = "BLOCK"
      input_action   = "BLOCK"
      output_action  = "BLOCK"
      input_enabled  = true
      output_enabled = true
    }
    pii_entities_config {
      type           = "AWS_SECRET_KEY"
      action         = "BLOCK"
      input_action   = "BLOCK"
      output_action  = "BLOCK"
      input_enabled  = true
      output_enabled = true
    }
    pii_entities_config {
      type           = "EMAIL"
      action         = "ANONYMIZE"
      input_action   = "ANONYMIZE"
      output_action  = "ANONYMIZE"
      input_enabled  = true
      output_enabled = true
    }
    pii_entities_config {
      type           = "PHONE"
      action         = "ANONYMIZE"
      input_action   = "ANONYMIZE"
      output_action  = "ANONYMIZE"
      input_enabled  = true
      output_enabled = true
    }
  }

  # Profanity filter
  word_policy_config {
    managed_word_lists_config {
      type           = "PROFANITY"
      input_action   = "BLOCK"
      output_action  = "BLOCK"
      input_enabled  = true
      output_enabled = true
    }
  }

  # No contextual grounding: the agents query live Redshift rather than RAG, and analytical summaries would trip it

  tags = {
    Name         = "${var.PrefixCode}-guardrail-agent"
    resourcetype = "security"
    codeblock    = "80-bedrock-guardrails"
  }
}

# Pinned guardrail version: a description change creates a new version, skip_destroy keeps the old ones
resource "aws_bedrock_guardrail_version" "agent" {
  guardrail_arn = aws_bedrock_guardrail.agent.guardrail_arn
  description   = "v5 — description no longer references an internal policy baseline"
  skip_destroy  = true
}
