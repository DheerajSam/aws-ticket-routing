# ─────────────────────────────────────────────────────────────
# variables.tf — Input variables for ticket routing infra
# ─────────────────────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "ap-south-1"  # Mumbai — closest to Chennai
}

variable "bucket_name" {
  description = "S3 bucket name for ticket routing data"
  type        = string
  default     = "ticket-routing-dheeraj"
}

variable "notification_email" {
  description = "Email address to receive assignment notifications"
  type        = string
  # Set this in terraform.tfvars — do not hardcode email here
}
