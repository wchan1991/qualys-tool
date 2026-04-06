#!/usr/bin/env python3
"""
Qualys Scan Manager - CLI

Command-line interface for scan management.

Usage:
    python cli.py health        # Test API connection
    python cli.py refresh       # Fetch scans from Qualys
    python cli.py list          # List scans from local database
    python cli.py stage pause <ref>   # Stage a pause action
    python cli.py staged        # Show staged changes
    python cli.py apply         # Apply staged changes
    python cli.py tags          # Show tag report
"""

import sys
import json
import argparse
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.config_loader import load_config
from src.scan_manager import ScanManager
from src.api_client import QualysError


def cmd_health(args) -> int:
    """Test API connectivity."""
    config = load_config()
    issues = config.validate()
    
    if issues:
        print("❌ Configuration issues:")
        for issue in issues:
            print(f"   - {issue}")
        return 1
    
    print(f"API URL: {config.api_url}")
    
    try:
        with ScanManager(config) as manager:
            profiles = manager.client.list_option_profiles()
            print(f"✅ Connected! Found {len(profiles)} option profiles.")
            return 0
    except QualysError as e:
        print(f"❌ Error: {e.message}")
        return 1


def cmd_refresh(args) -> int:
    """Refresh scans from Qualys."""
    with ScanManager() as manager:
        try:
            count = manager.refresh_scans()
            print(f"✅ Refreshed {count} scans")
            return 0
        except QualysError as e:
            print(f"❌ Error: {e.message}")
            return 1


def cmd_list(args) -> int:
    """List scans from local database."""
    with ScanManager() as manager:
        scans = manager.get_scans()
        
        if args.json:
            print(json.dumps(scans, indent=2))
            return 0
        
        print(f"\n{'=' * 60}")
        print(f"SCANS ({len(scans)} total)")
        print("=" * 60)
        
        for scan in scans:
            status = scan.get("status", "Unknown")
            icons = {
                "Running": "▶️ ",
                "Paused": "⏸️ ",
                "Queued": "⏳",
                "Finished": "✅",
                "Error": "❌",
            }
            icon = icons.get(status, "  ")
            
            print(f"\n{icon} {scan.get('title', 'Untitled')}")
            print(f"   Ref: {scan.get('ref', '')}")
            print(f"   Target: {scan.get('target', '')}")
            print(f"   Status: {status}")
            
            tags = scan.get("tags", [])
            if tags:
                print(f"   Tags: {', '.join(tags)}")
        
        return 0


def cmd_stage(args) -> int:
    """Stage an action."""
    with ScanManager() as manager:
        action = args.action
        scan_ref = args.scan_ref
        reason = args.reason or ""
        
        if action == "pause":
            change_id = manager.stage_pause(scan_ref, reason)
        elif action == "resume":
            change_id = manager.stage_resume(scan_ref, reason)
        elif action == "cancel":
            change_id = manager.stage_cancel(scan_ref, reason)
        else:
            print(f"Unknown action: {action}")
            return 1
        
        print(f"✅ Staged {action} for {scan_ref} (ID: {change_id})")
        return 0


def cmd_staged(args) -> int:
    """Show staged changes."""
    with ScanManager() as manager:
        changes = manager.get_staged_changes()
        
        if args.json:
            print(json.dumps(changes, indent=2))
            return 0
        
        print(f"\n📋 STAGED CHANGES ({len(changes)} pending)")
        print("=" * 50)
        
        if not changes:
            print("No staged changes.")
            return 0
        
        for change in changes:
            print(f"\n  [{change['id']}] {change['action'].upper()} → {change['scan_ref']}")
            print(f"      {change['description']}")
            print(f"      Staged: {change['staged_at']}")
        
        print(f"\nRun 'python cli.py apply' to execute these changes.")
        return 0


def cmd_apply(args) -> int:
    """Apply staged changes."""
    with ScanManager() as manager:
        changes = manager.get_staged_changes()
        
        if not changes:
            print("No staged changes to apply.")
            return 0
        
        if not args.yes:
            print(f"About to apply {len(changes)} changes:")
            for c in changes:
                print(f"  - {c['action']} → {c['scan_ref']}")
            
            confirm = input("\nProceed? [y/N] ")
            if confirm.lower() != 'y':
                print("Aborted.")
                return 0
        
        results = manager.apply_staged_changes()
        
        print(f"\n✅ Applied {results['success']}/{results['total']} changes")
        
        if results['failed'] > 0:
            print(f"❌ {results['failed']} failed:")
            for d in results['details']:
                if d['status'] != 'success':
                    print(f"   - {d['scan_ref']}: {d.get('error', 'Unknown error')}")
        
        return 0 if results['failed'] == 0 else 1


def cmd_discard(args) -> int:
    """Discard staged changes."""
    with ScanManager() as manager:
        if args.all:
            count = manager.discard_all_staged()
            print(f"✅ Discarded {count} changes")
        elif args.id:
            manager.discard_staged(args.id)
            print(f"✅ Discarded change {args.id}")
        else:
            print("Specify --all or --id")
            return 1
        
        return 0


def cmd_tags(args) -> int:
    """Show tag report."""
    with ScanManager() as manager:
        report = manager.get_tag_report()
        
        if args.json:
            print(json.dumps(report, indent=2))
            return 0
        
        print(f"\n🏷️  TAG REPORT ({len(report)} tags)")
        print("=" * 50)
        
        if not report:
            print("No tags found. Run 'python cli.py refresh' first.")
            return 0
        
        for tag in report:
            print(f"\n  {tag['tag']}")
            print(f"      Scans: {tag['scan_count']}")
            examples = tag.get('example_scans', [])
            if examples:
                print(f"      Examples: {', '.join(examples[:3])}")
        
        return 0


def cmd_dashboard(args) -> int:
    """Show dashboard."""
    with ScanManager() as manager:
        dashboard = manager.get_dashboard()
        
        if args.json:
            print(json.dumps(dashboard, indent=2))
            return 0
        
        print("""
┌────────────────────────────────────────┐
│          QUALYS SCAN DASHBOARD         │
├────────────────────────────────────────┤""")
        print(f"│  Total Scans:     {dashboard['total_scans']:>4}                 │")
        print(f"│  Running:         {dashboard['running']:>4}                 │")
        print(f"│  Paused:          {dashboard['paused']:>4}                 │")
        print(f"│  Queued:          {dashboard['queued']:>4}                 │")
        print(f"│  Finished:        {dashboard['finished']:>4}                 │")
        print(f"│  Pending Changes: {dashboard['pending_changes']:>4}                 │")
        print("└────────────────────────────────────────┘")
        
        if dashboard['last_refresh']:
            print(f"\nLast refresh: {dashboard['last_refresh']}")
        
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Qualys Scan Manager CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("-v", "--verbose", action="store_true")
    
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # Health
    subparsers.add_parser("health", help="Test API connection")
    
    # Refresh
    subparsers.add_parser("refresh", help="Fetch scans from Qualys")
    
    # List
    list_p = subparsers.add_parser("list", help="List scans")
    list_p.add_argument("--json", action="store_true")
    
    # Stage
    stage_p = subparsers.add_parser("stage", help="Stage an action")
    stage_p.add_argument("action", choices=["pause", "resume", "cancel"])
    stage_p.add_argument("scan_ref", help="Scan reference ID")
    stage_p.add_argument("--reason", help="Reason for the action")
    
    # Staged
    staged_p = subparsers.add_parser("staged", help="Show staged changes")
    staged_p.add_argument("--json", action="store_true")
    
    # Apply
    apply_p = subparsers.add_parser("apply", help="Apply staged changes")
    apply_p.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    
    # Discard
    discard_p = subparsers.add_parser("discard", help="Discard staged changes")
    discard_p.add_argument("--all", action="store_true")
    discard_p.add_argument("--id", type=int)
    
    # Tags
    tags_p = subparsers.add_parser("tags", help="Show tag report")
    tags_p.add_argument("--json", action="store_true")
    
    # Dashboard
    dash_p = subparsers.add_parser("dashboard", help="Show dashboard")
    dash_p.add_argument("--json", action="store_true")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)
    
    commands = {
        "health": cmd_health,
        "refresh": cmd_refresh,
        "list": cmd_list,
        "stage": cmd_stage,
        "staged": cmd_staged,
        "apply": cmd_apply,
        "discard": cmd_discard,
        "tags": cmd_tags,
        "dashboard": cmd_dashboard,
    }
    
    if args.command in commands:
        return commands[args.command](args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
