# ─────────────────────────────────────────────────────────────
# main.tf — 3WT Ticket Routing Infrastructure
# Provisions everything built manually in AWS Console
# ─────────────────────────────────────────────────────────────

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.3.0"
}

provider "aws" {
  region = var.aws_region
}

# ─────────────────────────────────────────────────────────────
# S3 BUCKET
# ─────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "ticket_routing" {
  bucket = var.bucket_name

  tags = {
    Project = "ticket-routing"
  }
}

# Block all public access
resource "aws_s3_bucket_public_access_block" "ticket_routing" {
  bucket                  = aws_s3_bucket.ticket_routing.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SSE-S3 encryption (matches what you set in console)
resource "aws_s3_bucket_server_side_encryption_configuration" "ticket_routing" {
  bucket = aws_s3_bucket.ticket_routing.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# Create folder structure via placeholder objects
resource "aws_s3_object" "folders" {
  for_each = toset([
    "ticket-routing-raw/",
    "ticket-routing-config/",
    "ticket-routing-processed/",
    "ticket-routing-output/",
  ])

  bucket  = aws_s3_bucket.ticket_routing.id
  key     = each.value
  content = ""
}


# ─────────────────────────────────────────────────────────────
# IAM ROLE FOR LAMBDA
# ─────────────────────────────────────────────────────────────

resource "aws_iam_role" "lambda_role" {
  name = "ticket-routing-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = {
    Project = "ticket-routing"
  }
}

# Attach managed policies (same 3 you added in console)
resource "aws_iam_role_policy_attachment" "s3_full" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_iam_role_policy_attachment" "sns_full" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSNSFullAccess"
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}


# ─────────────────────────────────────────────────────────────
# LAMBDA FUNCTIONS
# ─────────────────────────────────────────────────────────────

# Package Lambda 1 code into zip
data "archive_file" "lambda_fetch_zip" {
  type        = "zip"
  source_file = "${path.module}/../lambda_fetch/lambda_function.py"
  output_path = "${path.module}/zips/lambda_fetch.zip"
}

# Package Lambda 2 code into zip
data "archive_file" "lambda_assign_zip" {
  type        = "zip"
  source_file = "${path.module}/../lambda_assign/lambda_function.py"
  output_path = "${path.module}/zips/lambda_assign.zip"
}

# Lambda 1 — Fetch
resource "aws_lambda_function" "fetch" {
  function_name    = "ticket-routing-fetch"
  role             = aws_iam_role.lambda_role.arn
  runtime          = "python3.12"
  handler          = "lambda_function.lambda_handler"
  filename         = data.archive_file.lambda_fetch_zip.output_path
  source_code_hash = data.archive_file.lambda_fetch_zip.output_base64sha256
  timeout          = 60

  environment {
    variables = {
      S3_BUCKET = var.bucket_name
    }
  }

  tags = {
    Project = "ticket-routing"
  }
}

# Lambda 2 — Assign
resource "aws_lambda_function" "assign" {
  function_name    = "ticket-routing-assign"
  role             = aws_iam_role.lambda_role.arn
  runtime          = "python3.12"
  handler          = "lambda_function.lambda_handler"
  filename         = data.archive_file.lambda_assign_zip.output_path
  source_code_hash = data.archive_file.lambda_assign_zip.output_base64sha256
  timeout          = 60

  environment {
    variables = {
      S3_BUCKET     = var.bucket_name
      FULL_REFRESH  = "true"
      SNS_TOPIC_ARN = aws_sns_topic.notifications.arn
    }
  }

  tags = {
    Project = "ticket-routing"
  }
}


# ─────────────────────────────────────────────────────────────
# SNS TOPIC + EMAIL SUBSCRIPTION
# ─────────────────────────────────────────────────────────────

resource "aws_sns_topic" "notifications" {
  name = "ticket-routing-notifications"

  tags = {
    Project = "ticket-routing"
  }
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.notifications.arn
  protocol  = "email"
  endpoint  = var.notification_email
}


# ─────────────────────────────────────────────────────────────
# IAM ROLE FOR EVENTBRIDGE SCHEDULER
# ─────────────────────────────────────────────────────────────

resource "aws_iam_role" "scheduler_role" {
  name = "ticket-routing-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_lambda_invoke" {
  name = "invoke-lambda"
  role = aws_iam_role.scheduler_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = [
        aws_lambda_function.fetch.arn,
        aws_lambda_function.assign.arn
      ]
    }]
  })
}


# ─────────────────────────────────────────────────────────────
# EVENTBRIDGE SCHEDULER
# ─────────────────────────────────────────────────────────────

# Trigger Lambda 1 at 9:00 AM IST (3:30 AM UTC) daily
resource "aws_scheduler_schedule" "fetch" {
  name       = "ticket-routing-fetch-schedule"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  # 9:00 AM IST = 3:30 AM UTC
  schedule_expression          = "cron(30 3 * * ? *)"
  schedule_expression_timezone = "Asia/Kolkata"

  target {
    arn      = aws_lambda_function.fetch.arn
    role_arn = aws_iam_role.scheduler_role.arn
    input    = jsonencode({})
  }
}

# Trigger Lambda 2 at 9:05 AM IST (3:35 AM UTC) daily
resource "aws_scheduler_schedule" "assign" {
  name       = "ticket-routing-assign-schedule"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  # 9:05 AM IST = 3:35 AM UTC
  schedule_expression          = "cron(35 3 * * ? *)"
  schedule_expression_timezone = "Asia/Kolkata"

  target {
    arn      = aws_lambda_function.assign.arn
    role_arn = aws_iam_role.scheduler_role.arn
    input    = jsonencode({})
  }
}
