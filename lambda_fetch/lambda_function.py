"""
Lambda 1 — Ticket Fetcher
--------------------------
Reads INTL and NAM CSV files from S3 (uploaded via Coefficient export),
parses them into clean JSON, and saves back to S3 for Lambda 2 to process.

S3 Structure:
  INPUT:  ticket-routing-raw/intl.csv
          ticket-routing-raw/nam.csv
          ticket-routing-config/agent_attendance.csv
          ticket-routing-config/merchant_assignment.csv

  OUTPUT: ticket-routing-processed/intl.json
          ticket-routing-processed/nam.json
          ticket-routing-processed/agent_attendance.json
          ticket-routing-processed/merchant_assignment.json
"""

import boto3
import csv
import json
import io
import os
from datetime import datetime, timezone

s3 = boto3.client("s3")
BUCKET = os.environ.get("S3_BUCKET", "ticket-routing-bucket")


def parse_csv_from_s3(key, skip_coefficient_header=True):
    """Read a CSV from S3 and return list of dicts."""
    response = s3.get_object(Bucket=BUCKET, Key=key)
    content = response["Body"].read().decode("utf-8")
    lines = content.splitlines()

    if skip_coefficient_header:
        # Coefficient banner spans 2 merged lines before the real header
        # Scan forward until we find the actual "Case Number" header line
        for i, line in enumerate(lines):
            if line.startswith("Case Number"):
                lines = lines[i:]
                break

    reader = csv.DictReader(lines)
    return [dict(row) for row in reader]


def save_json_to_s3(data, key):
    """Save Python object as JSON to S3."""
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(data, indent=2),
        ContentType="application/json"
    )
    print(f"Saved {len(data)} records to s3://{BUCKET}/{key}")


def lambda_handler(event, context):
    print(f"Starting fetch at {datetime.now(timezone.utc).isoformat()}")

    # --- INTL Queue ---
    intl_data = parse_csv_from_s3("ticket-routing-raw/intl.csv")
    save_json_to_s3(intl_data, "ticket-routing-processed/intl.json")

    # --- NAM Queue ---
    nam_data = parse_csv_from_s3("ticket-routing-raw/nam.csv")
    save_json_to_s3(nam_data, "ticket-routing-processed/nam.json")

    # --- Agent Attendance ---
    attendance_data = parse_csv_from_s3(
        "ticket-routing-config/agent_attendance.csv",
        skip_coefficient_header=False
    )
    save_json_to_s3(attendance_data, "ticket-routing-processed/agent_attendance.json")

    # --- Merchant Assignment ---
    merchant_data = parse_csv_from_s3(
        "ticket-routing-config/merchant_assignment.csv",
        skip_coefficient_header=False
    )
    save_json_to_s3(merchant_data, "ticket-routing-processed/merchant_assignment.json")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Fetch complete",
            "intl_count": len(intl_data),
            "nam_count": len(nam_data),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    }
