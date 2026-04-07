#!/usr/bin/env python3
"""
Qualys Scan Manager - Web Application

Browser-based interface using Flask.
Run: python app.py
Open: http://localhost:5000

Thread-safety: The ScanDatabase class uses thread-local storage for SQLite
connections, making it safe to use with Flask's threaded mode.
"""

import shutil
import sys
import logging
import threading
from datetime import datetime
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, jsonify, request, redirect, url_for

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.config_loader import load_config
from src.scan_manager import ScanManager
from src.api_client import QualysError

# ============================================================
# APP SETUP
# ============================================================

app = Flask(__name__)
app.secret_key = "qualys-scan-manager-dev-key"  # Change in production

# Ensure directories exist before logging setup
Path("logs").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global manager instance - thread-safe due to database's thread-local connections
_manager = None
_config = None


def get_config():
    """Get or load configuration."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_manager() -> ScanManager:
    """
    Get or create the scan manager.

    The manager is a singleton, but the underlying database uses thread-local
    connections to ensure thread safety with Flask's threaded mode.
    """
    global _manager
    if _manager is None:
        _manager = ScanManager(get_config())
    return _manager


# ============================================================
# STARTUP — backup + clear on every launch (Feature 1)
# ============================================================

_startup_done = False

# Init gate (F22): block non-init routes while first refresh is running
_init_lock = threading.Lock()
_init_in_progress = False

_ALLOWED_DURING_INIT = {
    "/init",
    "/api/health",
    "/api/refresh-all",
    "/api/target-sources",
    "/api/backups",
}


def _perform_startup_backup() -> None:
    """Copy the live DB to data/backups/ before clearing it."""
    try:
        db_path = Path(get_config().db_path)
        if not db_path.exists() or db_path.stat().st_size == 0:
            return
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / f"qualys_scans_{stamp}.db"
        shutil.copy2(db_path, dest)
        logger.info(f"Startup backup created: {dest}")
    except Exception as e:
        logger.warning(f"Could not create startup backup: {e}")


@app.before_request
def run_startup():
    """Back up then clear scan data on first request after each app launch."""
    global _startup_done, _init_in_progress
    if not _startup_done:
        _startup_done = True
        _perform_startup_backup()
        try:
            get_manager().db.clear_scan_data()
            logger.info("Scan data cleared for fresh session")
            # Arm the init gate — will be released when /api/refresh-all completes
            with _init_lock:
                _init_in_progress = True
        except Exception as e:
            logger.warning(f"Could not clear scan data on startup: {e}")


@app.before_request
def gate_during_init():
    """
    While init is in progress, redirect non-essential routes to /init.

    Prevents a user who bookmarks /scheduled (etc.) from landing on a
    half-populated page during the first refresh after launch.
    """
    if not _init_in_progress:
        return
    path = request.path or ""
    # Always allow the init page itself, static assets, and the APIs it calls
    if path in _ALLOWED_DURING_INIT or path.startswith("/static/") or path.startswith("/api/backups/"):
        return
    # For JSON API callers: respond with JSON instead of a redirect
    if path.startswith("/api/"):
        return jsonify({"success": False, "error": "Initialization in progress"}), 503
    return redirect(url_for("init_page"))


def api_response(f):
    """Decorator for JSON API endpoints with error handling."""
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            result = f(*args, **kwargs)
            return jsonify({"success": True, "data": result})
        except QualysError as e:
            logger.error(f"Qualys API error: {e.message}")
            return jsonify({"success": False, "error": e.message}), 500
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    return decorated


# ============================================================
# PAGE ROUTES
# ============================================================

@app.route("/")
def index():
    """Main dashboard page — redirect to /init when DB is empty."""
    config = get_config()
    if get_manager().db.is_empty():
        return redirect(url_for("init_page"))
    return render_template(
        "index.html",
        configured=config.is_configured(),
        api_url=config.api_url,
    )


@app.route("/init")
def init_page():
    """Initialization / data-loading page."""
    return render_template("init.html")


@app.route("/scans")
def scans_page():
    """Recent/completed scans list page."""
    return render_template("scans.html")


@app.route("/scheduled")
def scheduled_page():
    """Scheduled scans page."""
    return render_template("scheduled.html")


@app.route("/staging")
def staging_page():
    """Staging review page."""
    return render_template("staging.html")


@app.route("/tags")
def tags_page():
    """Tag report page."""
    return render_template("tags.html")


@app.route("/scans/<path:scan_ref>")
def scan_detail_page(scan_ref):
    """Scan detail page."""
    return render_template("scan_detail.html", scan_ref=scan_ref)


@app.route("/scheduled/new")
def scheduled_new_page():
    """Create new scheduled scan form."""
    return render_template("scan_form.html", mode="create_scheduled")


@app.route("/scheduled/<scan_id>/edit")
def scheduled_edit_page(scan_id):
    """Edit scheduled scan form."""
    return render_template("scan_form.html", mode="edit_scheduled", scan_id=scan_id)


@app.route("/scheduled/<scan_id>")
def scheduled_detail_page(scan_id):
    """Scheduled scan detail page."""
    return render_template("scheduled_detail.html", scan_id=scan_id)


@app.route("/scans/new")
def scan_launch_page():
    """Launch on-demand scan form."""
    return render_template("scan_form.html", mode="launch")


@app.route("/lookup")
def lookup_page():
    """Target reverse lookup page."""
    return render_template("target_lookup.html")


@app.route("/calendar")
def calendar_page():
    """Calendar view."""
    return render_template("calendar.html")


@app.route("/scanners")
def scanners_page():
    """Scanner appliances page."""
    return render_template("scanners.html")


# ============================================================
# API ROUTES
# ============================================================

@app.route("/api/health")
@api_response
def api_health():
    """Check API connectivity."""
    config = get_config()
    issues = config.validate()
    
    if issues:
        return {"status": "unconfigured", "issues": issues}
    
    try:
        manager = get_manager()
        profiles = manager.client.list_option_profiles()
        return {
            "status": "connected",
            "api_url": config.api_url,
            "profiles": len(profiles)
        }
    except QualysError as e:
        return {"status": "error", "message": e.message}


@app.route("/api/dashboard")
@api_response
def api_dashboard():
    """Get dashboard metrics."""
    manager = get_manager()
    return manager.get_dashboard()


@app.route("/api/scans")
@api_response
def api_scans():
    """Get scans from local database."""
    manager = get_manager()
    return manager.get_scans()


@app.route("/api/scans/refresh", methods=["POST"])
@api_response
def api_refresh_scans():
    """Refresh scans from Qualys API."""
    manager = get_manager()
    count = manager.refresh_scans()
    return {"refreshed": count}


@app.route("/api/staged")
@api_response
def api_staged():
    """Get staged changes."""
    manager = get_manager()
    return manager.get_staged_changes()


@app.route("/api/stage", methods=["POST"])
@api_response
def api_stage():
    """Stage an action."""
    data = request.json
    action = data.get("action")
    scan_ref = data.get("scan_ref")
    reason = data.get("reason", "")
    
    if not action or not scan_ref:
        raise ValueError("action and scan_ref required")
    
    manager = get_manager()
    
    if action == "pause":
        change_id = manager.stage_pause(scan_ref, reason)
    elif action == "resume":
        change_id = manager.stage_resume(scan_ref, reason)
    elif action == "cancel":
        change_id = manager.stage_cancel(scan_ref, reason)
    # Scheduled scan actions
    elif action == "activate":
        title = data.get("title", "")
        change_id = manager.stage_activate(scan_ref, title, reason)
    elif action == "deactivate":
        title = data.get("title", "")
        change_id = manager.stage_deactivate(scan_ref, title, reason)
    elif action == "delete":
        title = data.get("title", "")
        change_id = manager.stage_delete_scheduled(scan_ref, title, reason)
    # Payload-based create / modify / launch
    elif action == "create_scheduled":
        payload = data.get("payload")
        if not payload:
            raise ValueError("payload required for create_scheduled")
        change_id = manager.stage_create_scheduled(payload, reason)
    elif action == "modify_scheduled":
        if not scan_ref:
            raise ValueError("scan_ref required for modify_scheduled")
        current = data.get("current", {})
        changes = data.get("changes", {})
        if not changes:
            raise ValueError("changes required for modify_scheduled")
        change_id = manager.stage_modify_scheduled(scan_ref, current, changes, reason)
    elif action == "launch":
        payload = data.get("payload")
        if not payload:
            raise ValueError("payload required for launch")
        change_id = manager.stage_launch_scan(payload, reason)
    else:
        raise ValueError(f"Unknown action: {action}")

    return {"change_id": change_id, "action": action, "scan_ref": scan_ref}


@app.route("/api/staged/<int:change_id>", methods=["DELETE"])
@api_response
def api_discard_change(change_id):
    """Discard a staged change."""
    manager = get_manager()
    manager.discard_staged(change_id)
    return {"discarded": change_id}


@app.route("/api/staged/all", methods=["DELETE"])
@api_response
def api_discard_all():
    """Discard all staged changes."""
    manager = get_manager()
    count = manager.discard_all_staged()
    return {"discarded": count}


@app.route("/api/apply", methods=["POST"])
@api_response
def api_apply():
    """Apply all staged changes."""
    manager = get_manager()
    results = manager.apply_staged_changes()
    return results


@app.route("/api/tags")
@api_response
def api_tags():
    """Get tag report."""
    manager = get_manager()
    return manager.get_tag_report()


@app.route("/api/scanners")
@api_response
def api_scanners():
    """Get scanner appliances."""
    manager = get_manager()
    return manager.get_scanners()


# ============================================================
# SCHEDULED SCAN API ROUTES
# ============================================================

@app.route("/api/scheduled")
@api_response
def api_scheduled_scans():
    """Get scheduled scans from local database."""
    manager = get_manager()
    return manager.get_scheduled_scans()


@app.route("/api/scheduled/refresh", methods=["POST"])
@api_response
def api_refresh_scheduled():
    """Refresh scheduled scans from Qualys API."""
    manager = get_manager()
    count = manager.refresh_scheduled_scans()
    return {"refreshed": count}


@app.route("/api/scheduled/debug", methods=["GET"])
@api_response
def api_scheduled_debug():
    """
    Debug endpoint - fetch raw scheduled scans from Qualys API.
    
    Returns the raw XML response and parsed results.
    Also saves the full raw XML to logs/scheduled_scans_debug.xml for inspection.
    
    Use this to troubleshoot parsing issues.
    """
    import os
    from datetime import datetime
    
    manager = get_manager()
    
    try:
        # Get raw response
        response = manager.client._request(
            "GET", "/api/2.0/fo/schedule/scan/",
            params={"action": "list"},
            timeout=90
        )
        
        raw_xml = response.text
        
        # Save full XML to file for debugging
        debug_file = os.path.join("logs", f"scheduled_scans_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml")
        os.makedirs("logs", exist_ok=True)
        with open(debug_file, "w", encoding="utf-8") as f:
            f.write(raw_xml)
        
        # Parse the XML to show structure
        import xml.etree.ElementTree as ET
        root = ET.fromstring(raw_xml)
        
        # Build structure info
        structure = []
        def walk(elem, depth=0):
            if depth > 4:  # Limit depth
                return
            children = list(elem)
            child_tags = [c.tag for c in children[:10]]  # First 10 children
            text_preview = (elem.text or "")[:50].strip()
            structure.append({
                "depth": depth,
                "tag": elem.tag,
                "children_count": len(children),
                "child_tags": child_tags,
                "text_preview": text_preview if text_preview else None,
                "attributes": dict(elem.attrib) if elem.attrib else None
            })
            for child in children[:5]:  # Only recurse first 5
                walk(child, depth + 1)
        
        walk(root)
        
        # Try to parse with our parser
        scheduled = manager.client._parse_scheduled(raw_xml)
        
        # Find SCAN elements with different XPaths for debugging
        xpath_results = {
            ".//SCAN": len(root.findall(".//SCAN")),
            ".//SCHEDULE_SCAN_LIST/SCAN": len(root.findall(".//SCHEDULE_SCAN_LIST/SCAN")),
            ".//RESPONSE/SCHEDULE_SCAN_LIST/SCAN": len(root.findall(".//RESPONSE/SCHEDULE_SCAN_LIST/SCAN")),
            ".//SCHEDULE_SCAN_LIST": len(root.findall(".//SCHEDULE_SCAN_LIST")),
        }
        
        return {
            "raw_xml_length": len(raw_xml),
            "raw_xml_preview": raw_xml[:3000],  # First 3000 chars
            "debug_file_saved": debug_file,
            "root_element": root.tag,
            "xml_structure": structure[:30],  # First 30 elements
            "xpath_results": xpath_results,
            "parsed_count": len(scheduled),
            "parsed_scans": scheduled[:5] if scheduled else [],  # First 5 scans
        }
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
        }


@app.route("/api/refresh-all", methods=["POST"])
@api_response
def api_refresh_all():
    """Refresh both running and scheduled scans from Qualys API."""
    global _init_in_progress
    manager = get_manager()
    try:
        counts = manager.refresh_all()
        return counts
    finally:
        # Release the init gate regardless of success/failure so the user
        # can navigate (and a failed init still lets them click Retry).
        with _init_lock:
            _init_in_progress = False


# ============================================================
# BULK STAGING (Feature 10)
# ============================================================

@app.route("/api/stage/bulk", methods=["POST"])
@api_response
def api_stage_bulk():
    """Stage multiple actions in one request."""
    data = request.json or {}
    changes = data.get("changes", [])
    if not changes:
        raise ValueError("changes list is required")

    manager = get_manager()
    staged = 0
    failed = []

    # F18: cache scheduled-scan list once so modify_option_profile lookups
    # don't hit the DB per row.
    _sched_cache = None

    def _sched_by_id(scan_id: str):
        nonlocal _sched_cache
        if _sched_cache is None:
            _sched_cache = {
                s.get("id") or s.get("scan_id"): s
                for s in (manager.get_scheduled_scans() or [])
            }
        return _sched_cache.get(scan_id)

    for item in changes:
        action = item.get("action", "")
        scan_ref = item.get("scan_ref", "")
        reason = item.get("reason", "")
        title = item.get("title", "")
        try:
            if action == "pause":
                manager.stage_pause(scan_ref, reason)
            elif action == "resume":
                manager.stage_resume(scan_ref, reason)
            elif action == "cancel":
                manager.stage_cancel(scan_ref, reason)
            elif action == "activate":
                manager.stage_activate(scan_ref, title, reason)
            elif action == "deactivate":
                manager.stage_deactivate(scan_ref, title, reason)
            elif action == "delete":
                manager.stage_delete_scheduled(scan_ref, title, reason)
            elif action == "modify_option_profile":
                new_profile = (item.get("option_profile") or "").strip()
                if not new_profile:
                    raise ValueError("option_profile required")
                current = _sched_by_id(scan_ref)
                if not current:
                    raise ValueError(f"Scheduled scan {scan_ref} not found")
                manager.stage_modify_scheduled(
                    scan_id=scan_ref,
                    current=current,
                    changes={"option_profile": new_profile},
                    reason=reason or f"Change option profile to {new_profile}",
                )
            else:
                raise ValueError(f"Unknown action: {action}")
            staged += 1
        except Exception as e:
            failed.append({"scan_ref": scan_ref, "action": action, "error": str(e)})

    return {"staged": staged, "failed": failed}


# ============================================================
# DETAIL API ROUTES
# ============================================================

@app.route("/api/scans/<path:scan_ref>/detail")
@api_response
def api_scan_detail(scan_ref):
    """Get full detail for a running/completed scan."""
    manager = get_manager()
    return manager.get_scan_detail(scan_ref)


@app.route("/api/scheduled/<scan_id>/detail")
@api_response
def api_scheduled_detail(scan_id):
    """Get full detail for a scheduled scan."""
    manager = get_manager()
    return manager.get_scheduled_scan_detail(scan_id)


# ============================================================
# REVERSE LOOKUP API
# ============================================================

@app.route("/api/lookup")
@api_response
def api_lookup():
    """Reverse target lookup: find scans using a given target."""
    target_type = request.args.get("type", "ip")
    target_value = request.args.get("value", "").strip()
    if not target_value:
        raise ValueError("value query parameter is required")
    manager = get_manager()
    return manager.find_scans_using_target(target_type, target_value)


@app.route("/api/scans/by-status")
@api_response
def api_scans_by_status():
    """
    F25: return scans that match a status, in the same shape as /api/lookup
    ({scheduled: [...], recent: [...]}), so the lookup page's existing
    renderer can display the results directly.
    """
    status = (request.args.get("status") or "").strip().lower()
    if not status:
        raise ValueError("status query parameter is required")
    return get_manager().get_scans_by_status(status)


# ============================================================
# TARGET SOURCES (for form dropdowns)
# ============================================================

@app.route("/api/target-sources")
@api_response
def api_target_sources():
    """Get asset groups, tags, scanners, and option profiles for form dropdowns."""
    manager = get_manager()
    return manager.get_target_sources()


# ============================================================
# CALENDAR API
# ============================================================

@app.route("/api/calendar")
@api_response
def api_calendar():
    """Get calendar events for FullCalendar."""
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    event_type = request.args.get("type", "scheduled")
    if not start or not end:
        raise ValueError("start and end query parameters are required")
    manager = get_manager()
    return manager.get_calendar_events(start, end, event_type)


# ============================================================
# BACKUP MANAGEMENT (Feature 1)
# ============================================================

@app.route("/api/backups")
@api_response
def api_list_backups():
    """List available DB backups."""
    db_path = Path(get_config().db_path)
    backup_dir = db_path.parent / "backups"
    if not backup_dir.exists():
        return []
    files = sorted(backup_dir.glob("qualys_scans_*.db"), reverse=True)
    return [
        {
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "created": datetime.fromtimestamp(f.stat().st_mtime).astimezone().isoformat(),
        }
        for f in files
    ]


@app.route("/api/backups/restore/<filename>", methods=["POST"])
@api_response
def api_restore_backup(filename):
    """Restore a named backup over the live DB."""
    global _manager
    # Validate filename — no path separators or traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError("Invalid filename")
    db_path = Path(get_config().db_path)
    src = db_path.parent / "backups" / filename
    if not src.exists():
        raise FileNotFoundError(f"Backup not found: {filename}")
    # Close existing connections before overwriting
    if _manager is not None:
        try:
            _manager.db.close()
        except Exception:
            pass
        _manager = None
    shutil.copy2(src, db_path)
    logger.info(f"Restored backup: {filename}")
    return {"restored": filename}


# ============================================================
# DASHBOARD TRAFFIC CHART (Feature 6)
# ============================================================

@app.route("/api/dashboard/traffic")
@api_response
def api_dashboard_traffic():
    """Get 24-hour scan launch traffic for the dashboard chart."""
    manager = get_manager()
    return manager.db.get_scan_traffic_24h()


@app.route("/api/dashboard/forecast")
@api_response
def api_dashboard_forecast():
    """
    F20: forecast scheduled scan launches for the next N hours (24, 48, 72).
    Returns the same shape as /api/dashboard/traffic — a list of
    {hour, count} buckets — so the dashboard chart can swap modes
    without changing its rendering code.
    """
    try:
        hours = int(request.args.get("hours", "24"))
    except ValueError:
        hours = 24
    if hours not in (24, 48, 72):
        hours = 24
    return get_manager().get_launch_forecast(hours)


@app.route("/api/scans/recent")
@api_response
def api_scans_recent():
    """
    F13: scans launched within the last N hours (default 6). Used by the
    Dashboard "Recent Scans (last 6 hours)" panel.
    """
    try:
        hours = int(request.args.get("hours", "6"))
    except ValueError:
        hours = 6
    return get_manager().db.get_recent_scans(hours)


# ============================================================
# TOP TAGS (Feature 11)
# ============================================================

@app.route("/api/tags/top")
@api_response
def api_tags_top():
    """Get top tags by scan count."""
    limit = int(request.args.get("limit", 10))
    manager = get_manager()
    return manager.db.get_top_tags(limit)


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", error="Page not found"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", error="Server error"), 500


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  Qualys Scan Manager")
    print("  Open: http://localhost:5000")
    print("=" * 50 + "\n")
    
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        threaded=True
    )
