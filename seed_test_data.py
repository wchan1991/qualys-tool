#!/usr/bin/env python3
"""
Test Data Seeder

Populates the SQLite database with realistic dummy data for visual/UI testing.
Run this, then launch app.py with invalid credentials to test in offline mode.

Usage:
    python seed_test_data.py
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.database import ScanDatabase, ChangeType


def seed():
    db_path = Path("data/qualys_scans.db")
    db_path.parent.mkdir(exist_ok=True)
    db = ScanDatabase(str(db_path))

    # Clear existing data
    db.clear_scan_data()
    db.conn.execute("DELETE FROM staged_changes")
    db.conn.commit()

    now = datetime.now(timezone.utc)

    # ── Running / completed scans ──────────────────────────────
    scans = [
        {
            "ref": "scan/1718234001.12345",
            "title": "Weekly PCI Compliance Scan",
            "target": "10.0.1.0/24",
            "status": "Running",
            "type": "Vulnerability",
            "option_profile": "PCI Quarterly External",
            "launched": (now - timedelta(hours=2)).strftime("%Y/%m/%d %H:%M:%S"),
            "duration": "02:14:33",
            "tags": ["PCI", "Production", "External"],
        },
        {
            "ref": "scan/1718234002.22345",
            "title": "DMZ Perimeter Assessment",
            "target": "192.168.1.1-192.168.1.50",
            "status": "Running",
            "type": "Vulnerability",
            "option_profile": "Full Audit",
            "launched": (now - timedelta(hours=1)).strftime("%Y/%m/%d %H:%M:%S"),
            "duration": "01:05:12",
            "tags": ["DMZ", "Perimeter"],
        },
        {
            "ref": "scan/1718234003.33345",
            "title": "Ad-hoc Patch Verification",
            "target": "10.10.5.22",
            "status": "Paused",
            "type": "Vulnerability",
            "option_profile": "Patch Tuesday",
            "launched": (now - timedelta(hours=4)).strftime("%Y/%m/%d %H:%M:%S"),
            "duration": "00:45:00",
            "tags": ["Patching"],
        },
        {
            "ref": "scan/1718234004.44345",
            "title": "Staging Environment Baseline",
            "target": "172.16.0.0/16",
            "status": "Queued",
            "type": "Vulnerability",
            "option_profile": "Initial Options",
            "launched": now.strftime("%Y/%m/%d %H:%M:%S"),
            "duration": "",
            "tags": ["Staging", "Baseline"],
        },
        {
            "ref": "scan/1718234005.55345",
            "title": "Nightly Internal Scan - US East",
            "target": "10.20.0.0/16",
            "status": "Finished",
            "type": "Vulnerability",
            "option_profile": "Standard",
            "launched": (now - timedelta(hours=8)).strftime("%Y/%m/%d %H:%M:%S"),
            "duration": "03:22:10",
            "tags": ["Internal", "US-East", "Nightly"],
            "processed": 1247,
            "total_hosts": 1310,
        },
        {
            "ref": "scan/1718234006.66345",
            "title": "Nightly Internal Scan - US West",
            "target": "10.30.0.0/16",
            "status": "Finished",
            "type": "Vulnerability",
            "option_profile": "Standard",
            "launched": (now - timedelta(hours=7)).strftime("%Y/%m/%d %H:%M:%S"),
            "duration": "02:58:44",
            "tags": ["Internal", "US-West", "Nightly"],
            "processed": 983,
            "total_hosts": 983,
        },
        {
            "ref": "scan/1718234007.77345",
            "title": "Cloud Asset Discovery",
            "target": "aws-prod-vpc.example.com",
            "status": "Finished",
            "type": "Discovery",
            "option_profile": "Cloud Discovery",
            "launched": (now - timedelta(hours=12)).strftime("%Y/%m/%d %H:%M:%S"),
            "duration": "01:15:00",
            "tags": ["Cloud", "AWS", "Discovery"],
            "processed": 156,
            "total_hosts": 160,
        },
        {
            "ref": "scan/1718234008.88345",
            "title": "Web App Scan - Customer Portal",
            "target": "portal.example.com",
            "status": "Error",
            "type": "Vulnerability",
            "option_profile": "Web Application",
            "launched": (now - timedelta(hours=3)).strftime("%Y/%m/%d %H:%M:%S"),
            "duration": "00:12:05",
            "tags": ["WebApp", "Production"],
            "processed": 0,
            "total_hosts": 1,
        },
        {
            "ref": "scan/1718234009.99345",
            "title": "Database Server Audit",
            "target": "10.0.5.10, 10.0.5.11, 10.0.5.12",
            "status": "Canceled",
            "type": "Vulnerability",
            "option_profile": "Database Audit",
            "launched": (now - timedelta(hours=6)).strftime("%Y/%m/%d %H:%M:%S"),
            "duration": "00:33:20",
            "tags": ["Database", "Audit"],
            "processed": 1,
            "total_hosts": 3,
        },
        {
            "ref": "scan/1718234010.10345",
            "title": "Executive Summary - Q2 2026",
            "target": "10.0.0.0/8",
            "status": "Finished",
            "type": "Vulnerability",
            "option_profile": "Executive Summary",
            "launched": (now - timedelta(hours=20)).strftime("%Y/%m/%d %H:%M:%S"),
            "duration": "06:45:00",
            "tags": ["Executive", "Quarterly", "Production"],
            "processed": 4521,
            "total_hosts": 4600,
        },
        {
            "ref": "scan/1718234011.11345",
            "title": "Container Image Scan",
            "target": "172.17.0.0/24",
            "status": "Running",
            "type": "Vulnerability",
            "option_profile": "Container Security",
            "launched": (now - timedelta(minutes=30)).strftime("%Y/%m/%d %H:%M:%S"),
            "duration": "00:30:00",
            "tags": ["Container", "DevOps"],
        },
        {
            "ref": "scan/1718234012.12345",
            "title": "IoT Device Inventory",
            "target": "10.50.0.0/24",
            "status": "Queued",
            "type": "Discovery",
            "option_profile": "IoT Discovery",
            "launched": now.strftime("%Y/%m/%d %H:%M:%S"),
            "duration": "",
            "tags": ["IoT", "Discovery"],
        },
    ]

    count = db.save_scans(scans)
    print(f"  Inserted {count} running/completed scans")

    # ── Scheduled scans ────────────────────────────────────────
    scheduled = [
        {
            "id": "900001",
            "title": "Daily PCI Perimeter Scan",
            "target": "10.0.1.0/24, 10.0.2.0/24",
            "active": True,
            "status": "active",
            "option_profile": "PCI Quarterly External",
            "scanner": "scanner01.example.com",
            "schedule": "Daily (every 1 day) at 02:00",
            "next_launch": (now + timedelta(hours=6)).strftime("%Y/%m/%d %H:%M:%S"),
            "last_launch": (now - timedelta(hours=18)).strftime("%Y/%m/%d %H:%M:%S"),
            "owner": "admin@example.com",
            "tags": ["PCI", "Perimeter"],
            "targets": [
                {"type": "ip", "value": "10.0.1.0/24"},
                {"type": "ip", "value": "10.0.2.0/24"},
                {"type": "tag", "value": "PCI"},
            ],
            "type": "scheduled",
        },
        {
            "id": "900002",
            "title": "Weekly Full Internal Audit",
            "target": "10.0.0.0/8",
            "active": True,
            "status": "active",
            "option_profile": "Full Audit",
            "scanner": "scanner02.example.com",
            "schedule": "Weekly (Sun) at 01:00",
            "next_launch": (now + timedelta(days=3)).strftime("%Y/%m/%d %H:%M:%S"),
            "last_launch": (now - timedelta(days=4)).strftime("%Y/%m/%d %H:%M:%S"),
            "owner": "security-team@example.com",
            "tags": ["Internal", "Audit"],
            "targets": [
                {"type": "range", "value": "10.0.0.1-10.0.255.254"},
                {"type": "tag", "value": "Internal"},
            ],
            "type": "scheduled",
        },
        {
            "id": "900003",
            "title": "Monthly Executive Report Scan",
            "target": "All Production Assets",
            "active": True,
            "status": "active",
            "option_profile": "Executive Summary",
            "scanner": "scanner01.example.com",
            "schedule": "Monthly (1st) at 00:00",
            "next_launch": (now + timedelta(days=20)).strftime("%Y/%m/%d %H:%M:%S"),
            "last_launch": (now - timedelta(days=10)).strftime("%Y/%m/%d %H:%M:%S"),
            "owner": "ciso@example.com",
            "tags": ["Executive", "Production"],
            "targets": [
                {"type": "asset_group", "value": "All Production Assets"},
                {"type": "tag", "value": "Production"},
            ],
            "type": "scheduled",
        },
        {
            "id": "900004",
            "title": "Nightly DMZ Scan",
            "target": "192.168.1.0/24",
            "active": False,
            "status": "paused",
            "option_profile": "Standard",
            "scanner": "scanner03.example.com",
            "schedule": "Daily (every 1 day) at 23:00",
            "next_launch": "",
            "last_launch": (now - timedelta(days=2)).strftime("%Y/%m/%d %H:%M:%S"),
            "owner": "admin@example.com",
            "tags": ["DMZ", "Nightly"],
            "targets": [
                {"type": "ip", "value": "192.168.1.0/24"},
                {"type": "tag", "value": "DMZ"},
            ],
            "type": "scheduled",
        },
        {
            "id": "900005",
            "title": "Web Application Scan - Staging",
            "target": "staging.example.com",
            "active": False,
            "status": "inactive",
            "option_profile": "Web Application",
            "scanner": "scanner02.example.com",
            "schedule": "Weekly (Mon, Wed, Fri) at 06:00",
            "next_launch": "",
            "last_launch": (now - timedelta(days=14)).strftime("%Y/%m/%d %H:%M:%S"),
            "owner": "devops@example.com",
            "tags": ["WebApp", "Staging"],
            "targets": [
                {"type": "ip", "value": "staging.example.com"},
                {"type": "tag", "value": "Staging"},
            ],
            "type": "scheduled",
        },
        {
            "id": "900006",
            "title": "Cloud Infrastructure - AWS Prod",
            "target": "aws-prod tagged assets",
            "active": True,
            "status": "active",
            "option_profile": "Cloud Discovery",
            "scanner": "cloud-scanner-aws.example.com",
            "schedule": "Daily (every 1 day) at 04:00",
            "next_launch": (now + timedelta(hours=10)).strftime("%Y/%m/%d %H:%M:%S"),
            "last_launch": (now - timedelta(hours=14)).strftime("%Y/%m/%d %H:%M:%S"),
            "owner": "cloud-team@example.com",
            "tags": ["Cloud", "AWS", "Production"],
            "targets": [
                {"type": "tag", "value": "Cloud"},
                {"type": "tag", "value": "AWS"},
            ],
            "type": "scheduled",
        },
        {
            "id": "900007",
            "title": "Compliance Scan - SOX Controls",
            "target": "10.100.0.0/16",
            "active": True,
            "status": "active",
            "option_profile": "SOX Compliance",
            "scanner": "scanner01.example.com",
            "schedule": "Weekly (Tue, Thu) at 03:00",
            "next_launch": (now + timedelta(days=1)).strftime("%Y/%m/%d %H:%M:%S"),
            "last_launch": (now - timedelta(days=2)).strftime("%Y/%m/%d %H:%M:%S"),
            "owner": "compliance@example.com",
            "tags": ["SOX", "Compliance"],
            "targets": [
                {"type": "range", "value": "10.100.0.1-10.100.255.254"},
                {"type": "tag", "value": "SOX"},
            ],
            "type": "scheduled",
        },
        {
            "id": "900008",
            "title": "Legacy Systems - End of Life Check",
            "target": "10.200.1.0/24",
            "active": False,
            "status": "inactive",
            "option_profile": "Standard",
            "scanner": "scanner03.example.com",
            "schedule": "Monthly (15th) at 22:00",
            "next_launch": "",
            "last_launch": (now - timedelta(days=45)).strftime("%Y/%m/%d %H:%M:%S"),
            "owner": "admin@example.com",
            "tags": ["Legacy", "EOL"],
            "targets": [
                {"type": "ip", "value": "10.200.1.0/24"},
            ],
            "type": "scheduled",
        },
        {
            "id": "900009",
            "title": "Database Tier Vulnerability Scan",
            "target": "10.0.5.10, 10.0.5.11, 10.0.5.12",
            "active": True,
            "status": "active",
            "option_profile": "Database Audit",
            "scanner": "scanner02.example.com",
            "schedule": "Daily (every 1 day) at 05:00",
            "next_launch": (now + timedelta(hours=8)).strftime("%Y/%m/%d %H:%M:%S"),
            "last_launch": (now - timedelta(hours=19)).strftime("%Y/%m/%d %H:%M:%S"),
            "owner": "dba-team@example.com",
            "tags": ["Database", "Production"],
            "targets": [
                {"type": "ip", "value": "10.0.5.10"},
                {"type": "ip", "value": "10.0.5.11"},
                {"type": "ip", "value": "10.0.5.12"},
                {"type": "tag", "value": "Database"},
            ],
            "type": "scheduled",
        },
    ]

    sched_count = db.save_scheduled_scans(scheduled)
    print(f"  Inserted {sched_count} scheduled scans")

    # ── Staged changes ─────────────────────────────────────────
    staged = [
        {
            "scan_ref": "scan/1718234001.12345",
            "change_type": ChangeType.PAUSE,
            "description": "Pause: Weekly PCI Compliance Scan",
            "scan_type": "scan",
            "old_value": "Running",
            "new_value": "Paused",
        },
        {
            "scan_ref": "900004",
            "change_type": ChangeType.DEACTIVATE,
            "description": "Deactivate: Nightly DMZ Scan",
            "scan_type": "scheduled",
            "old_value": "active",
            "new_value": "inactive",
        },
        {
            "scan_ref": "900008",
            "change_type": ChangeType.DELETE,
            "description": "Delete: Legacy Systems - End of Life Check",
            "scan_type": "scheduled",
            "old_value": "",
            "new_value": "",
        },
        {
            "scan_ref": "scan/1718234008.88345",
            "change_type": ChangeType.CANCEL,
            "description": "Cancel: Web App Scan - Customer Portal (Error state)",
            "scan_type": "scan",
            "old_value": "Error",
            "new_value": "Canceled",
        },
    ]

    for s in staged:
        db.stage_change(
            scan_ref=s["scan_ref"],
            change_type=s["change_type"],
            description=s["description"],
            scan_type=s["scan_type"],
            old_value=s["old_value"],
            new_value=s["new_value"],
        )
    print(f"  Inserted {len(staged)} staged changes")

    # ── Applied changes (changelog history) ──────────────────
    history = [
        {
            "scan_ref": "scan/1718230001.00001",
            "change_type": ChangeType.PAUSE,
            "description": "Pause: Nightly Full Scan - US East",
            "scan_type": "scan",
            "old_value": "Running",
            "new_value": "Paused",
            "hours_ago": 48,
        },
        {
            "scan_ref": "scan/1718230001.00001",
            "change_type": ChangeType.RESUME,
            "description": "Resume: Nightly Full Scan - US East",
            "scan_type": "scan",
            "old_value": "Paused",
            "new_value": "Running",
            "hours_ago": 46,
        },
        {
            "scan_ref": "900010",
            "change_type": ChangeType.DEACTIVATE,
            "description": "Deactivate: Weekly Compliance Scan (maintenance window)",
            "scan_type": "scheduled",
            "old_value": "active",
            "new_value": "inactive",
            "hours_ago": 36,
        },
        {
            "scan_ref": "900010",
            "change_type": ChangeType.ACTIVATE,
            "description": "Activate: Weekly Compliance Scan (maintenance complete)",
            "scan_type": "scheduled",
            "old_value": "inactive",
            "new_value": "active",
            "hours_ago": 24,
        },
        {
            "scan_ref": "scan/1718230002.00002",
            "change_type": ChangeType.CANCEL,
            "description": "Cancel: Ad-hoc pen test scan (wrong target)",
            "scan_type": "scan",
            "old_value": "Running",
            "new_value": "Canceled",
            "hours_ago": 12,
        },
        {
            "scan_ref": "900011",
            "change_type": ChangeType.DELETE,
            "description": "Delete: Deprecated quarterly scan",
            "scan_type": "scheduled",
            "old_value": "",
            "new_value": "",
            "hours_ago": 6,
        },
    ]

    for h in history:
        change_id = db.stage_change(
            scan_ref=h["scan_ref"],
            change_type=h["change_type"],
            description=h["description"],
            scan_type=h["scan_type"],
            old_value=h["old_value"],
            new_value=h["new_value"],
        )
        # Mark as applied with a timestamp
        applied_time = (now - timedelta(hours=h["hours_ago"])).isoformat()
        db.conn.execute(
            "UPDATE staged_changes SET applied = 1, applied_at = ? WHERE id = ?",
            (applied_time, change_id)
        )
    db.conn.commit()
    print(f"  Inserted {len(history)} changelog entries (applied changes)")

    db.close()
    print(f"\nDone! Database seeded at: {db_path}")
    print("Run 'python app.py' to launch in offline mode.")


if __name__ == "__main__":
    print("Seeding test data...")
    seed()
