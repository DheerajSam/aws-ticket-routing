"""
Lambda 2 — Ticket Assignment Engine
-------------------------------------
Reads processed JSON from S3, runs the exact same assignment logic
that was previously in Google Apps Script, and outputs assignments.

Assignment Rules:
  INTL: UUID mapped to specific agent (if present) → else least busy agent
  NAM:  Always least busy agent
        SKIP if Status == "open" AND last modified < 24 hours ago

Output saved to:
  ticket-routing-output/assignments-YYYY-MM-DD.json
  ticket-routing-output/assignments-YYYY-MM-DD.csv  (human readable)
"""

import boto3
import json
import csv
import io
import os
from datetime import datetime, timezone, timedelta

s3 = boto3.client("s3")
sns = boto3.client("sns")

BUCKET      = os.environ.get("S3_BUCKET", "ticket-routing-bucket")
SNS_TOPIC   = os.environ.get("SNS_TOPIC_ARN", "")  # Set in Lambda env vars
FULL_REFRESH = os.environ.get("FULL_REFRESH", "true").lower() == "true"


# ─────────────────────────────────────────────
# S3 Helpers
# ─────────────────────────────────────────────

def read_json(key):
    """Read JSON file from S3."""
    try:
        response = s3.get_object(Bucket=BUCKET, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except s3.exceptions.NoSuchKey:
        print(f"WARNING: {key} not found in S3.")
        return []


def save_json(data, key):
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(data, indent=2),
        ContentType="application/json"
    )


def save_csv(rows, fieldnames, key):
    """Save list of dicts as CSV to S3."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=buffer.getvalue(),
        ContentType="text/csv"
    )


# ─────────────────────────────────────────────
# Core Logic
# ─────────────────────────────────────────────

def get_active_agents(attendance_data):
    """Return list of agents marked Present."""
    return [
        row["Agent Name"].strip()
        for row in attendance_data
        if row.get("Attendance", "").strip().lower() == "present"
    ]


def build_merchant_map(merchant_data, active_agents):
    """
    Build UUID → Agent Name map.
    Only include mappings where agent is currently present.
    Matches Apps Script: merchantMap[uuid] = agentName
    """
    merchant_map = {}
    for row in merchant_data:
        uuid  = row.get("Merchant UUID", "").strip()
        agent = row.get("Agent Name", "").strip()
        if uuid and agent and agent in active_agents:
            merchant_map[uuid] = agent
    return merchant_map


def get_least_busy(agent_stats):
    """Return agent with lowest current ticket count."""
    return min(agent_stats, key=agent_stats.get)


def is_nam_eligible(row, now):
    """
    NAM filter: Skip if Status == 'open' AND modified within last 24 hours.
    Matches Apps Script NAM filter logic exactly.
    """
    status = row.get("Status", "").strip().lower()
    last_mod_str = row.get("Case Date/Time Last Modified", "").strip()

    if status != "open":
        return True  # Not open → always eligible

    if not last_mod_str:
        return True  # No date → assume eligible

    try:
        # Date format in CSV: DD/MM/YYYY HH:MM
        last_mod = datetime.strptime(last_mod_str, "%d/%m/%Y %H:%M")
        last_mod = last_mod.replace(tzinfo=timezone.utc)
        hours_since = (now - last_mod).total_seconds() / 3600
        if hours_since < 24:
            return False  # Open + modified recently → skip
    except ValueError:
        print(f"Could not parse date: {last_mod_str}")

    return True


def assign_tickets(intl_data, nam_data, active_agents, merchant_map, existing_cases):
    """
    Core assignment function.
    Mirrors Apps Script processData() logic exactly.
    """
    agent_stats = {agent: 0 for agent in active_agents}
    now = datetime.now(timezone.utc)
    assignments = []

    # ── INTL: UUID-based mapping, fallback to least busy ──
    for row in intl_data:
        case_num = row.get("Case Number", "").strip()
        if not case_num or case_num in existing_cases:
            continue

        uuid   = row.get("Merchant UUID", "").strip()
        mapped = merchant_map.get(uuid)

        # Use mapped agent if present, else least busy
        assigned = mapped if mapped else get_least_busy(agent_stats)
        agent_stats[assigned] += 1

        assignments.append({
            "Case Number":      case_num,
            "Assigned Agent":   assigned,
            "Queue":            "INTL",
            "Country":          row.get("Country", ""),
            "Status":           row.get("Status", ""),
            "Case Record Type": row.get("Case Record Type", ""),
            "Merchant UUID":    uuid,
            "Merchant Name":    row.get("Merchant Name", ""),
            "Age (Hours)":      row.get("Age (Hours)", ""),
        })

    # ── NAM: Always least busy, with 24h open filter ──
    for row in nam_data:
        case_num = row.get("Case Number", "").strip()
        if not case_num or case_num in existing_cases:
            continue

        if not is_nam_eligible(row, now):
            print(f"  Skipped NAM case {case_num} — Open + modified <24h ago")
            continue

        assigned = get_least_busy(agent_stats)
        agent_stats[assigned] += 1

        assignments.append({
            "Case Number":      case_num,
            "Assigned Agent":   assigned,
            "Queue":            "NAM",
            "Country":          row.get("Country", ""),
            "Status":           row.get("Status", ""),
            "Case Record Type": row.get("Case Record Type", ""),
            "Merchant UUID":    row.get("Merchant UUID", ""),
            "Merchant Name":    row.get("Merchant Name", ""),
            "Age (Hours)":      row.get("Age (Hours)", ""),
        })

    return assignments, agent_stats


# ─────────────────────────────────────────────
# SNS Notification
# ─────────────────────────────────────────────

def send_notification(assignments, agent_stats, date_str):
    """Send summary email via SNS."""
    if not SNS_TOPIC:
        print("No SNS topic configured — skipping notification.")
        return

    summary_lines = [
        f"✅ Ticket Assignment Complete — {date_str}",
        f"Total tickets assigned: {len(assignments)}",
        "",
        "📊 Agent Workload:",
    ]
    for agent, count in sorted(agent_stats.items()):
        summary_lines.append(f"  {agent}: {count} tickets")

    summary_lines += [
        "",
        f"📁 Output saved to S3: ticket-routing-output/assignments-{date_str}.csv"
    ]

    sns.publish(
        TopicArn=SNS_TOPIC,
        Subject=f"Ticket Assignment Report — {date_str}",
        Message="\n".join(summary_lines)
    )
    print("SNS notification sent.")


# ─────────────────────────────────────────────
# Lambda Handler
# ─────────────────────────────────────────────

def lambda_handler(event, context):
    print(f"Starting assignment at {datetime.now(timezone.utc).isoformat()}")
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Load all data from S3
    intl_data       = read_json("ticket-routing-processed/intl.json")
    nam_data        = read_json("ticket-routing-processed/nam.json")
    attendance_data = read_json("ticket-routing-processed/agent_attendance.json")
    merchant_data   = read_json("ticket-routing-processed/merchant_assignment.json")

    print(f"Loaded: {len(intl_data)} INTL, {len(nam_data)} NAM tickets")

    # 2. Get active agents
    active_agents = get_active_agents(attendance_data)
    if not active_agents:
        return {"statusCode": 400, "body": "No agents marked Present"}
    print(f"Active agents ({len(active_agents)}): {active_agents}")

    # 3. Build merchant → agent map
    merchant_map = build_merchant_map(merchant_data, active_agents)
    print(f"Merchant map: {len(merchant_map)} UUID → agent mappings loaded")

    # 4. Track already-assigned cases (incremental mode)
    existing_cases = set()
    if not FULL_REFRESH:
        existing_output = read_json(f"ticket-routing-output/assignments-{date_str}.json")
        existing_cases  = {r["Case Number"] for r in existing_output}
        print(f"Incremental mode: {len(existing_cases)} cases already assigned today")

    # 5. Run assignment
    assignments, agent_stats = assign_tickets(
        intl_data, nam_data, active_agents, merchant_map, existing_cases
    )
    print(f"Assigned {len(assignments)} tickets")
    print(f"Agent workload: {agent_stats}")

    # 6. Save outputs
    output_json_key = f"ticket-routing-output/assignments-{date_str}.json"
    output_csv_key  = f"ticket-routing-output/assignments-{date_str}.csv"

    fieldnames = [
        "Case Number", "Assigned Agent", "Queue", "Country",
        "Status", "Case Record Type", "Merchant UUID", "Merchant Name", "Age (Hours)"
    ]

    save_json(assignments, output_json_key)
    save_csv(assignments, fieldnames, output_csv_key)
    print(f"Saved JSON: {output_json_key}")
    print(f"Saved CSV:  {output_csv_key}")

    # 7. Send notification
    send_notification(assignments, agent_stats, date_str)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "tickets_assigned": len(assignments),
            "active_agents":    active_agents,
            "agent_workload":   agent_stats,
            "output_csv":       f"s3://{BUCKET}/{output_csv_key}",
            "timestamp":        datetime.now(timezone.utc).isoformat()
        })
    }
