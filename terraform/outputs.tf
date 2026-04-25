# ─────────────────────────────────────────────────────────────
# outputs.tf — Useful values after terraform apply
# ─────────────────────────────────────────────────────────────

output "s3_bucket_name" {
  description = "S3 bucket for ticket routing"
  value       = aws_s3_bucket.ticket_routing.bucket
}

output "lambda_fetch_arn" {
  description = "ARN of the fetch Lambda function"
  value       = aws_lambda_function.fetch.arn
}

output "lambda_assign_arn" {
  description = "ARN of the assign Lambda function"
  value       = aws_lambda_function.assign.arn
}

output "sns_topic_arn" {
  description = "ARN of the SNS notification topic"
  value       = aws_sns_topic.notifications.arn
}

output "fetch_schedule" {
  description = "Cron schedule for fetch Lambda"
  value       = aws_scheduler_schedule.fetch.schedule_expression
}

output "assign_schedule" {
  description = "Cron schedule for assign Lambda"
  value       = aws_scheduler_schedule.assign.schedule_expression
}
