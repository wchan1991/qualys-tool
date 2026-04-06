"""
Scan Manager

High-level operations for scan management with staging support.
Supports both running scans and scheduled scans.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

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
            # Running scans
            "total_scans": len(scans),
            "running": status_counts.get("Running", 0),
            "paused": status_counts.get("Paused", 0),
            "queued": status_counts.get("Queued", 0),
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
