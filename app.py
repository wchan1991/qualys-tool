#!/usr/bin/env python3
"""
Qualys Scan Manager - Web Application

Browser-based interface using Flask.
Run: python app.py
Open: http://localhost:5000

Thread-safety: The ScanDatabase class uses thread-local storage for SQLite
connections, making it safe to use with Flask's threaded mode.
"""

import sys
import logging
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, jsonify, request

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
    """Main dashboard page."""
    config = get_config()
    
    return render_template(
        "index.html",
        configured=config.is_configured(),
        api_url=config.api_url,
    )


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
    manager = get_manager()
    counts = manager.refresh_all()
    return counts


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
