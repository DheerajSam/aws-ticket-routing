# AWS Serverless Ticket Routing System

Migrated a production ticket routing system from Google Sheets + Apps Script 
to a fully serverless AWS architecture.

## Problem
A customer service team handling 440+ daily tickets across INTL and NAM queues 
required manual report downloads and agent assignment — a slow, error-prone process.

## Solution
Built a serverless pipeline on AWS that automates the entire workflow daily.

## Architecture

S3 (raw CSVs) → Lambda 1 (fetch) → S3 (JSON) → Lambda 2 (assign) → SNS (email agents)

EventBridge Scheduler triggers pipeline automatically at 9:30 PM IST daily

## Assignment Logic
- **INTL queue:** Merchant UUID mapped to dedicated agents, fallback to least busy
- **NAM queue:** Load balanced across active agents, skips cases open < 24 hours
- **Result:** 443 tickets distributed evenly across 6 agents in under 1 second

## AWS Services Used
- AWS Lambda (Python 3.12)
- Amazon S3
- Amazon SNS
- Amazon EventBridge Scheduler
- AWS IAM

## Infrastructure as Code
All resources provisioned using Terraform.

## Impact
- Eliminated manual report downloads and ticket assignment
- Added automated email notifications to agents
- Reduced assignment time from minutes to under 1 second


