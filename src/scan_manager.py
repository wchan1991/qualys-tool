"""
Scan Manager

High-level operations for scan management with staging support.
Supports both running scans and scheduled scans.
"""

import ipaddress
import json
import logging
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone

from dateutil import rrule as rrulemod
from dateutil.parser import parse as parse_dt
from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY

from .config_loader import QualysConfig, load_config
from .api_client import QualysClient, QualysError
from .database import ScanDatabase, ChangeType, StagedChange

logger = logging.getLogger(__name__)


class ScanManager:
    """
    Manages scans with staging (review before apply).
    
    Key features:
    - Fetch and store scans locally (running and scheduled)
    - Stage changes for review
    - Apply staged changes with "Make it so" action
    - Diff comparison
    - Tag reporting
    """
    
    def __init__(self, config: QualysConfig = None):
        self.config = config or load_config()
        self.db = ScanDatabase(self.config.db_path)
        self._client: Optional[QualysClient] = None
    
    @property
    def client(self) -> QualysClient:
        """Lazy-load API client."""
        if self._client is None:
            self._client = QualysClient(self.config)
        return self._client
    
    # ========================================================
    # SYNC OPERATIONS - RUNNING SCANS
    # ========================================================
    
    def refresh_scans(self) -> int:
        """
        Fetch latest scans from Qualys and store locally.
        
        Returns:
            Number of scans saved
        """
        logger.info("Fetching scans from Qualys API...")
        
        try:
            scans = self.client.list_scans()
            count = self.db.save_scans(scans)
            logger.info(f"Refreshed {count} scans")
            return count
        except QualysError as e:
            logger.error(f"Failed to refresh scans: {e.message}")
            raise
    
    def get_scans(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Get running/completed scans from local database.
        
        Args:
            refresh: If True, fetch fresh from API first
        """
        if refresh:
            self.refresh_scans()
        
        records = self.db.get_latest_scans()
        return [
            {
                "ref": r.ref,
                "title": r.title,
                "target": r.target,
                "status": r.status,
                "type": r.scan_type,
                "option_profile": r.option_profile,
                "launched": r.launched,
                "duration": r.duration,
                "tags": r.get_tags(),
                "fetched_at": r.fetched_at,
            }
            for r in records
        ]
    
    # ========================================================
    # SYNC OPERATIONS - SCHEDULED SCANS
    # ========================================================
    
    def refresh_scheduled_scans(self) -> int:
        """
        Fetch scheduled scans from Qualys and store locally.
        
        Returns:
            Number of scheduled scans saved
        """
        logger.info("Fetching scheduled scans from Qualys API...")
        
        try:
            scans = self.client.list_scheduled_scans()
            count = self.db.save_scheduled_scans(scans)
            logger.info(f"Refreshed {count} scheduled scans")
            return count
        except QualysError as e:
            logger.error(f"Failed to refresh scheduled scans: {e.message}")
            raise
    
    def get_scheduled_scans(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Get scheduled scans from local database.
        
        Args:
            refresh: If True, fetch fresh from API first
        """
        if refresh:
            self.refresh_scheduled_scans()
        
        return self.db.get_latest_scheduled_scans()
    
    def refresh_all(self) -> Dict[str, int]:
        """
        Refresh both running scans and scheduled scans.
        
        Returns:
            Dict with counts for 'scans' and 'scheduled'
        """
        scans_count = self.refresh_scans()
        scheduled_count = self.refresh_scheduled_scans()
        return {
            "scans": scans_count,
            "scheduled": scheduled_count,
        }
    
    def get_scanners(self) -> List[Dict[str, Any]]:
        """Get scanner appliances."""
        return self.client.list_scanners()
    
    # ========================================================
    # STAGING OPERATIONS - RUNNING SCANS
    # ========================================================
    
    def stage_pause(self, scan_ref: str, reason: str = "") -> int:
        """Stage a pause action for review."""
        return self.db.stage_change(
            scan_ref,
            ChangeType.PAUSE,
            old_value="Running",
            new_value="Paused",
            description=reason or "Pause scan",
            scan_type="scan"
        )
    
    def stage_resume(self, scan_ref: str, reason: str = "") -> int:
        """Stage a resume action for review."""
        return self.db.stage_change(
            scan_ref,
            ChangeType.RESUME,
            old_value="Paused",
            new_value="Running",
            description=reason or "Resume scan",
            scan_type="scan"
        )
    
    def stage_cancel(self, scan_ref: str, reason: str = "") -> int:
        """Stage a cancel action for review."""
        return self.db.stage_change(
            scan_ref,
            ChangeType.CANCEL,
            old_value="Running",
            new_value="Canceled",
            description=reason or "Cancel scan",
            scan_type="scan"
        )
    
    # ========================================================
    # STAGING OPERATIONS - SCHEDULED SCANS
    # ========================================================
    
    def stage_activate(self, scan_id: str, title: str = "", reason: str = "") -> int:
        """Stage activation of a scheduled scan."""
        return self.db.stage_change(
            scan_id,
            ChangeType.ACTIVATE,
            old_value="Inactive",
            new_value="Active",
            description=reason or f"Activate scheduled scan: {title}",
            scan_type="scheduled"
        )
    
    def stage_deactivate(self, scan_id: str, title: str = "", reason: str = "") -> int:
        """Stage deactivation of a scheduled scan."""
        return self.db.stage_change(
            scan_id,
            ChangeType.DEACTIVATE,
            old_value="Active",
            new_value="Inactive",
            description=reason or f"Deactivate scheduled scan: {title}",
            scan_type="scheduled"
        )
    
    def stage_delete_scheduled(self, scan_id: str, title: str = "", reason: str = "") -> int:
        """Stage deletion of a scheduled scan."""
        return self.db.stage_change(
            scan_id,
            ChangeType.DELETE,
            old_value="Exists",
            new_value="Deleted",
            description=reason or f"Delete scheduled scan: {title}",
            scan_type="scheduled"
        )

    def stage_create_scheduled(self, payload: Dict[str, Any], reason: str = "") -> int:
        """Stage creation of a new scheduled scan."""
        title = payload.get("title", "New scheduled scan")
        return self.db.stage_change(
            scan_ref="__new__",
            change_type=ChangeType.CREATE,
            old_value="",
            new_value="Scheduled",
            description=reason or f"Create scheduled scan: {title}",
            scan_type="scheduled",
            payload=payload,
        )

    def stage_modify_scheduled(
        self,
        scan_id: str,
        current: Dict[str, Any],
        changes: Dict[str, Any],
        reason: str = "",
    ) -> int:
        """Stage a basic edit of a scheduled scan (title, target, option profile)."""
        title = changes.get("title") or current.get("title", scan_id)
        payload = {"scan_id": scan_id, "current": current, "changes": changes}
        return self.db.stage_change(
            scan_ref=scan_id,
            change_type=ChangeType.MODIFY,
            old_value=json.dumps(current),
            new_value=json.dumps(changes),
            description=reason or f"Edit scheduled scan: {title}",
            scan_type="scheduled",
            payload=payload,
        )

    def stage_launch_scan(self, payload: Dict[str, Any], reason: str = "") -> int:
        """Stage an on-demand scan launch."""
        title = payload.get("title", "On-demand scan")
        return self.db.stage_change(
            scan_ref="__launch__",
            change_type=ChangeType.LAUNCH,
            old_value="",
            new_value="Launched",
            description=reason or f"Launch scan: {title}",
            scan_type="scan",
            payload=payload,
        )

    # ========================================================
    # STAGING - COMMON
    # ========================================================
    
    def get_staged_changes(self) -> List[Dict[str, Any]]:
        """Get all pending staged changes."""
        changes = self.db.get_staged_changes(pending_only=True)
        return [
            {
                "id": c.id,
                "scan_ref": c.scan_ref,
                "scan_type": c.scan_type,
                "action": c.change_type,
                "description": c.description,
                "staged_at": c.staged_at,
                "payload": c.payload or None,
            }
            for c in changes
        ]
    
    def discard_staged(self, change_id: int) -> None:
        """Discard a staged change."""
        self.db.clear_staged_change(change_id)
    
    def discard_all_staged(self) -> int:
        """Discard all staged changes."""
        return self.db.clear_all_staged()
    
    # ========================================================
    # APPLY ("Make It So")
    # ========================================================
    
    def apply_staged_changes(self) -> Dict[str, Any]:
        """
        Apply all staged changes to Qualys.
        Supports both running scans and scheduled scans.
        
        Returns:
            Summary of results
        """
        changes = self.db.get_staged_changes(pending_only=True)
        
        results = {
            "total": len(changes),
            "success": 0,
            "failed": 0,
            "details": [],
        }
        
        for change in changes:
            try:
                success = False
                
                # Running scan operations
                if change.change_type == ChangeType.PAUSE.value:
                    success = self.client.pause_scan(change.scan_ref)
                elif change.change_type == ChangeType.RESUME.value:
                    success = self.client.resume_scan(change.scan_ref)
                elif change.change_type == ChangeType.CANCEL.value:
                    success = self.client.cancel_scan(change.scan_ref)
                
                # Scheduled scan operations
                elif change.change_type == ChangeType.ACTIVATE.value:
                    success = self.client.activate_scheduled_scan(change.scan_ref)
                elif change.change_type == ChangeType.DEACTIVATE.value:
                    success = self.client.deactivate_scheduled_scan(change.scan_ref)
                elif change.change_type == ChangeType.DELETE.value:
                    success = self.client.delete_scheduled_scan(change.scan_ref)

                # Create / modify / launch operations (payload-based)
                elif change.change_type == ChangeType.LAUNCH.value:
                    payload = json.loads(change.payload) if change.payload else {}
                    scan_ref = self.client.launch_scan(payload)
                    success = bool(scan_ref)
                elif change.change_type == ChangeType.CREATE.value and change.scan_type == "scheduled":
                    payload = json.loads(change.payload) if change.payload else {}
                    new_id = self.client.create_scheduled_scan(payload)
                    success = bool(new_id)
                elif change.change_type == ChangeType.MODIFY.value and change.scan_type == "scheduled":
                    payload = json.loads(change.payload) if change.payload else {}
                    changes = payload.get("changes", {})
                    success = self.client.update_scheduled_scan(change.scan_ref, changes)
                
                if success:
                    self.db.mark_change_applied(change.id)
                    results["success"] += 1
                    results["details"].append({
                        "id": change.id,
                        "scan_ref": change.scan_ref,
                        "scan_type": change.scan_type,
                        "action": change.change_type,
                        "status": "success",
                    })
                else:
                    results["failed"] += 1
                    results["details"].append({
                        "id": change.id,
                        "scan_ref": change.scan_ref,
                        "scan_type": change.scan_type,
                        "action": change.change_type,
                        "status": "failed",
                        "error": "Operation returned false",
                    })
                    
            except QualysError as e:
                results["failed"] += 1
                results["details"].append({
                    "id": change.id,
                    "scan_ref": change.scan_ref,
                    "scan_type": change.scan_type,
                    "action": change.change_type,
                    "status": "error",
                    "error": str(e.message),
                })
        
        logger.info(
            f"Applied {results['success']}/{results['total']} changes "
            f"({results['failed']} failed)"
        )
        
        return results
    
    # ========================================================
    # DETAIL PAGES
    # ========================================================

    def get_scan_detail(self, scan_ref: str) -> Dict[str, Any]:
        """Get full detail for a running/completed scan."""
        return self.client.get_scan_detail(scan_ref)

    def get_scheduled_scan_detail(self, scan_id: str) -> Dict[str, Any]:
        """Get full detail for a scheduled scan."""
        scans = self.client.get_scheduled_scan(scan_id)
        if scans:
            return scans[0]
        return {}

    # ========================================================
    # REVERSE TARGET LOOKUP
    # ========================================================

    def find_scans_using_target(self, target_type: str, target_value: str) -> Dict[str, Any]:
        """
        Find all scans (scheduled + recent) that use a given target.

        Args:
            target_type: One of 'ip', 'range', 'asset_group', 'tag', 'ip_list'
            target_value: The value to search for

        Returns:
            {'scheduled': [...], 'recent': [...]}
        """
        return self.db.find_scans_by_target(target_type, target_value)

    def get_scans_by_status(self, status: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        F25: return scans matching a status, in the same shape as
        find_scans_by_target so the lookup page can render them.

        Supported values:
          - Non-scheduled scan states: running, paused, queued, finished,
            canceled, error ("failed" is aliased to error).
          - Scheduled scan states: active, paused, inactive.
          - "all": every non-scheduled and scheduled scan.
        """
        status = (status or "").lower().strip()
        if status == "failed":
            status = "error"

        scheduled_out: List[Dict[str, Any]] = []
        recent_out: List[Dict[str, Any]] = []

        scans = self.get_scans() or []
        scheduled = self.get_scheduled_scans() or []

        if status == "all":
            recent_matches = scans
            scheduled_matches = scheduled
        elif status in ("active", "inactive"):
            scheduled_matches = [
                s for s in scheduled
                if (s.get("status") or ("active" if s.get("active") else "inactive")) == status
            ]
            recent_matches = []
        elif status == "paused":
            # "paused" exists for both scheduled and non-scheduled states
            scheduled_matches = [
                s for s in scheduled
                if (s.get("status") or "").lower() == "paused"
            ]
            recent_matches = [
                s for s in scans if (s.get("status") or "").lower() == "paused"
            ]
        else:
            scheduled_matches = []
            recent_matches = [
                s for s in scans if (s.get("status") or "").lower() == status
            ]

        for s in scheduled_matches:
            sid = s.get("id") or s.get("scan_id") or ""
            scheduled_out.append({
                "scan_id": sid,
                "title": s.get("title"),
                "active": bool(s.get("active")),
                "status": s.get("status") or ("active" if s.get("active") else "inactive"),
                "owner": s.get("owner"),
                "target": s.get("target"),
                "matched_target": f"status:{status}",
            })

        for r in recent_matches:
            recent_out.append({
                "ref": r.get("ref"),
                "title": r.get("title"),
                "status": r.get("status"),
                "owner": None,
                "target": r.get("target"),
                "matched_target": f"status:{status}",
            })

        return {"scheduled": scheduled_out, "recent": recent_out}

    # ========================================================
    # TARGET SOURCES (for form dropdowns)
    # ========================================================

    _target_sources_cache: Optional[Dict[str, Any]] = None
    _target_sources_fetched_at: Optional[float] = None
    _TARGET_SOURCES_TTL = 300  # 5 minutes

    def get_target_sources(self) -> Dict[str, Any]:
        """
        Return asset groups, tags, scanners, and option profiles for form dropdowns.
        Cached for 5 minutes.
        """
        now = time.monotonic()
        if (
            self._target_sources_cache is not None
            and self._target_sources_fetched_at is not None
            and now - self._target_sources_fetched_at < self._TARGET_SOURCES_TTL
        ):
            return self._target_sources_cache

        result: Dict[str, Any] = {
            "asset_groups": [],
            "tags": [],
            "scanners": [],
            "option_profiles": [],
            "top_targets": [],
        }

        try:
            result["asset_groups"] = self.client.list_asset_groups()
        except Exception as e:
            logger.warning(f"Could not fetch asset groups: {e}")

        try:
            result["tags"] = self.client.list_tags()
        except Exception as e:
            logger.warning(f"Could not fetch tags: {e}")

        try:
            result["scanners"] = self.client.list_scanners()
        except Exception as e:
            logger.warning(f"Could not fetch scanners: {e}")

        try:
            result["option_profiles"] = self.client.list_option_profiles()
        except Exception as e:
            logger.warning(f"Could not fetch option profiles: {e}")

        # F17: surface the most-used literal targets (from the local DB)
        # so the lookup page can render them as clickable chips.
        try:
            result["top_targets"] = self.db.get_top_targets(50)
        except Exception as e:
            logger.warning(f"Could not fetch top targets: {e}")

        ScanManager._target_sources_cache = result
        ScanManager._target_sources_fetched_at = now
        return result

    # ========================================================
    # CALENDAR
    # ========================================================

    def get_calendar_events(
        self,
        start_iso: str,
        end_iso: str,
        event_type: str = "scheduled",
    ) -> List[Dict[str, Any]]:
        """
        Return calendar events in a FullCalendar-compatible format.

        Args:
            start_iso: ISO8601 start of window
            end_iso:   ISO8601 end of window
            event_type: 'scheduled' or 'ondemand'

        Returns:
            List of {id, title, start, end, url, color, extendedProps}
        """
        try:
            start_dt = parse_dt(start_iso)
            end_dt = parse_dt(end_iso)
        except Exception:
            return []

        if event_type == "ondemand":
            return self._ondemand_events(start_dt, end_dt)
        return self._scheduled_events(start_dt, end_dt)

    def get_launch_forecast(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        F20: project active scheduled scans forward into hourly buckets so
        the dashboard chart can show "next 24/48/72h" forecasts.

        Returns a list of {hour, count} dicts ordered by time.
        """
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        end = now + timedelta(hours=hours)

        # Pre-seed buckets so the response is dense (includes zero hours)
        buckets: Dict[datetime, int] = {}
        for h in range(hours):
            buckets[now + timedelta(hours=h)] = 0

        scheduled = self.get_scheduled_scans()
        for scan in scheduled:
            if not scan.get("active"):
                continue
            try:
                occurrences = self._expand_schedule(scan, now, end)
            except Exception as e:
                logger.debug(
                    f"Forecast: could not expand schedule for "
                    f"{scan.get('id') or scan.get('scan_id')}: {e}"
                )
                continue
            for occ in occurrences:
                # _expand_schedule returns naive datetimes — treat as UTC
                occ_utc = occ.replace(tzinfo=timezone.utc) if occ.tzinfo is None else occ.astimezone(timezone.utc)
                bucket = occ_utc.replace(minute=0, second=0, microsecond=0)
                if bucket in buckets:
                    buckets[bucket] += 1

        return [
            {
                "hour": k.astimezone().strftime("%Y-%m-%d %H:00"),
                "count": v,
            }
            for k, v in sorted(buckets.items())
        ]

    def _ondemand_events(self, start_dt: datetime, end_dt: datetime) -> List[Dict[str, Any]]:
        """Historical on-demand scan events from the local DB."""
        scans = self.get_scans()
        events = []
        for scan in scans:
            launched_str = scan.get("launched")
            if not launched_str:
                continue
            try:
                launched = parse_dt(str(launched_str))
            except Exception:
                continue
            if not (start_dt.replace(tzinfo=None) <= launched.replace(tzinfo=None) <= end_dt.replace(tzinfo=None)):
                continue
            events.append({
                "id": scan["ref"],
                "title": scan.get("title") or scan["ref"],
                "start": launched.isoformat(),
                "url": f"/scans/{scan['ref']}",
                "color": self._status_color(scan.get("status", "")),
                "extendedProps": {
                    "status": scan.get("status"),
                    "target": scan.get("target"),
                    "ref": scan["ref"],
                },
            })
        return events

    def _scheduled_events(self, start_dt: datetime, end_dt: datetime) -> List[Dict[str, Any]]:
        """Project scheduled scan recurrences into concrete events."""
        scheduled = self.get_scheduled_scans()
        events = []

        for scan in scheduled:
            if not scan.get("active"):
                continue
            # The DB row uses "id" but earlier code mistakenly read "scan_id"
            # which produced empty URLs (F16). Accept both to be defensive.
            sid = scan.get("id") or scan.get("scan_id") or ""
            occurrences = self._expand_schedule(scan, start_dt, end_dt)
            for occ in occurrences:
                events.append({
                    "id": f"{sid}_{occ.isoformat()}",
                    "title": scan.get("title", "Scheduled Scan"),
                    "start": occ.isoformat(),
                    "url": f"/scheduled/{sid}" if sid else "",
                    "color": "#3788d8",
                    "extendedProps": {
                        "scan_id": sid,
                        "target": scan.get("target"),
                        "active": scan.get("active"),
                    },
                })

        return events

    def _expand_schedule(
        self, scan: Dict[str, Any], start_dt: datetime, end_dt: datetime
    ) -> List[datetime]:
        """
        Expand a scheduled scan's recurrence rule into datetimes within [start_dt, end_dt].
        Works with the schedule fields stored in the local DB row.
        """
        raw = scan.get("raw_data")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        if not raw:
            raw = {}

        # Parse start datetime from scan
        start_str = (
            raw.get("start_datetime")
            or raw.get("START_DATETIME")
            or scan.get("next_launch")
            or scan.get("start_date")
        )
        try:
            scan_start = parse_dt(str(start_str)) if start_str else start_dt
        except Exception:
            scan_start = start_dt

        # Make naive for comparison
        scan_start = scan_start.replace(tzinfo=None)
        win_start = start_dt.replace(tzinfo=None)
        win_end = end_dt.replace(tzinfo=None)

        occurrence = (raw.get("occurrence") or raw.get("OCCURRENCE") or "").lower()
        freq_days = raw.get("frequency_days") or raw.get("FREQUENCY_DAYS")
        freq_weeks = raw.get("frequency_weeks") or raw.get("FREQUENCY_WEEKS")

        try:
            if occurrence == "daily" or (freq_days and int(freq_days) > 0):
                interval = int(freq_days or 1)
                dates = list(rrule(DAILY, dtstart=scan_start, until=win_end, interval=interval))
            elif occurrence == "weekly" or (freq_weeks and int(freq_weeks) > 0):
                interval = int(freq_weeks or 1)
                weekdays_str = raw.get("weekdays") or raw.get("WEEKDAYS") or ""
                byweekday = self._parse_weekdays(weekdays_str)
                dates = list(rrule(WEEKLY, dtstart=scan_start, until=win_end, interval=interval, byweekday=byweekday or None))
            elif occurrence == "monthly":
                day_of_month = raw.get("day_of_month") or raw.get("DAY_OF_MONTH")
                if day_of_month:
                    dates = list(rrule(MONTHLY, dtstart=scan_start, until=win_end, bymonthday=int(day_of_month)))
                else:
                    dates = list(rrule(MONTHLY, dtstart=scan_start, until=win_end))
            else:
                # One-time or unknown — use scan_start if in window
                dates = [scan_start] if win_start <= scan_start <= win_end else []
        except Exception as e:
            logger.debug(f"Could not expand schedule for scan {scan.get('scan_id')}: {e}")
            dates = []

        return [d for d in dates if win_start <= d <= win_end]

    @staticmethod
    def _parse_weekdays(weekdays_str: str) -> list:
        """Convert 'sunday,monday,...' string to dateutil weekday constants."""
        _MAP = {
            "sunday": rrulemod.SU,
            "monday": rrulemod.MO,
            "tuesday": rrulemod.TU,
            "wednesday": rrulemod.WE,
            "thursday": rrulemod.TH,
            "friday": rrulemod.FR,
            "saturday": rrulemod.SA,
        }
        result = []
        for part in weekdays_str.lower().replace(";", ",").split(","):
            part = part.strip()
            if part in _MAP:
                result.append(_MAP[part])
        return result

    @staticmethod
    def _status_color(status: str) -> str:
        return {
            "Running": "#28a745",
            "Paused": "#ffc107",
            "Queued": "#17a2b8",
            "Finished": "#6c757d",
            "Error": "#dc3545",
            "Canceled": "#6c757d",
        }.get(status, "#6c757d")

    # ========================================================
    # DIFF / COMPARISON
    # ========================================================
    
    def get_diff(self, scan_ref: str) -> Dict[str, Any]:
        """Get diff between current state and staged changes."""
        return self.db.get_diff(scan_ref)
    
    def get_all_diffs(self) -> List[Dict[str, Any]]:
        """Get diffs for all scans with staged changes."""
        changes = self.db.get_staged_changes(pending_only=True)
        seen_refs = set()
        diffs = []
        
        for change in changes:
            if change.scan_ref not in seen_refs:
                seen_refs.add(change.scan_ref)
                diffs.append(self.get_diff(change.scan_ref))
        
        return diffs
    
    # ========================================================
    # TAG REPORTING
    # ========================================================
    
    def get_tag_report(self) -> List[Dict[str, Any]]:
        """Get tag usage report."""
        return self.db.get_tag_report()
    
    def get_scans_by_tag(self, tag: str) -> List[str]:
        """Get scans with a specific tag."""
        return self.db.get_scans_by_tag(tag)
    
    # ========================================================
    # DASHBOARD
    # ========================================================
    
    def get_dashboard(self) -> Dict[str, Any]:
        """Get dashboard metrics for both running and scheduled scans."""
        scans = self.get_scans()
        scheduled = self.get_scheduled_scans()
        staged = self.get_staged_changes()
        
        # Count running scans by status
        status_counts = {}
        for scan in scans:
            status = scan.get("status", "Unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Count scheduled scans by active status
        active_scheduled = sum(1 for s in scheduled if s.get("active"))
        inactive_scheduled = len(scheduled) - active_scheduled
        
        return {
            # Recent/running scans — Running and Queued removed per Feature 7
            "total_scans": len(scans),
            "paused": status_counts.get("Paused", 0),
            "finished": status_counts.get("Finished", 0),
            "failed": status_counts.get("Error", 0),
            # Scheduled scans
            "total_scheduled": len(scheduled),
            "active_scheduled": active_scheduled,
            "inactive_scheduled": inactive_scheduled,
            # Staging
            "pending_changes": len(staged),
            "last_refresh": scans[0]["fetched_at"] if scans else None,
        }
    
    # ========================================================
    # CLEANUP
    # ========================================================
    
    def close(self) -> None:
        """Clean up resources."""
        if self._client:
            self._client.close()
            self._client = None
        self.db.close()
    
    def __enter__(self) -> "ScanManager":
        return self
    
    def __exit__(self, *args) -> None:
        self.close()
