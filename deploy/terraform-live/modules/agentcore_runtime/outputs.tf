output "runtime_arn" {
  value = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn
}

output "runtime_id" {
  value = aws_bedrockagentcore_agent_runtime.this.agent_runtime_id
}

output "role_arn" {
  value = aws_iam_role.this.arn
}

output "vended_log_group_name" {
  value = aws_cloudwatch_log_group.vended.name
}

output "vended_log_group_arn" {
  value = aws_cloudwatch_log_group.vended.arn
}
