"""
Database Module

SQLite database for:
- Storing scan history (point-in-time snapshots)
- Staging area for changes before applying
- Diff comparison between staged and live
- Tag reporting

Thread-safe: Creates new connections per-thread for Flask compatibility.
"""

import sqlite3
import json
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class ChangeType(Enum):
    """Types of staged changes."""
    # Running scan operations
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    LAUNCH = "launch"  # one-shot on-demand scan
    # Scheduled scan operations
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"
    DELETE = "delete"
    # General (used for scheduled scan create/edit)
    CREATE = "create"
    MODIFY = "modify"


@dataclass
class ScanRecord:
    """A scan record stored in the database."""
    ref: str
    title: str
    target: str
    status: str
    scan_type: str
    option_profile: str
    launched: str
    duration: str
    tags: str  # JSON array
    raw_data: str  # Full JSON for future use
    fetched_at: str
    
    def get_tags(self) -> List[str]:
        """Parse tags from JSON string."""
        try:
            return json.loads(self.tags) if self.tags else []
        except json.JSONDecodeError:
            return []


@dataclass
class StagedChange:
    """A staged change pending approval."""
    id: int
    scan_ref: str
    scan_type: str  # 'scan' or 'scheduled'
    change_type: str
    old_value: str
    new_value: str
    staged_at: str
    description: str
    applied: bool = False
    payload: str = ""  # JSON blob for CREATE/MODIFY/LAUNCH (full config)


class ScanDatabase:
    """
    Thread-safe SQLite database for scan management.
    
    Creates a new connection for each thread to avoid SQLite threading issues.
    This is essential for Flask which uses multiple worker threads.
    
    Provides:
    - Historical snapshots of scans
    - Staging area for changes (review before apply)
    - Diff comparison
    - Tag analysis
    """
    
    def __init__(self, db_path: str = "data/qualys_scans.db"):
        """Initialize database path and create schema."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Thread-local storage for connections
        self._local = threading.local()
        
        # Initialize schema (creates connection for current thread)
        self._init_schema()
    
    def _get_connection(self) -> sqlite3.Connection:
        """
        Get or create a connection for the current thread.
        
        SQLite connections cannot be shared across threads safely.
        This method ensures each thread gets its own connection.
        """
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False  # We manage thread safety ourselves
            )
            self._local.conn.row_factory = sqlite3.Row
            logger.debug(f"Created new DB connection for thread {threading.current_thread().name}")
        return self._local.conn
    
    @property
    def conn(self) -> sqlite3.Connection:
        """Get connection for current thread."""
        return self._get_connection()
    
    def _init_schema(self) -> None:
        """Create tables if they don't exist and run migrations."""
        cursor = self.conn.cursor()
        
        # Scan snapshots (historical records of completed/running scans)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ref TEXT NOT NULL,
                title TEXT,
                target TEXT,
                status TEXT,
                scan_type TEXT,
                option_profile TEXT,
                launched TEXT,
                duration TEXT,
                tags TEXT,
                raw_data TEXT,
                fetched_at TEXT NOT NULL,
                UNIQUE(ref, fetched_at)
            )
        """)
        
        # Scheduled scans (recurring scan configurations)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT NOT NULL,
                title TEXT,
                target TEXT,
                active INTEGER,
                option_profile TEXT,
                scanner TEXT,
                schedule TEXT,
                next_launch TEXT,
                last_launch TEXT,
                owner TEXT,
                raw_data TEXT,
                fetched_at TEXT NOT NULL,
                UNIQUE(scan_id, fetched_at)
            )
        """)
        
        # Staging area for changes (supports both scan types)
        # payload TEXT carries the full JSON config for CREATE/MODIFY/LAUNCH
        # actions where old_value/new_value strings are insufficient.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS staged_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_ref TEXT NOT NULL,
                scan_type TEXT DEFAULT 'scan',
                change_type TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                staged_at TEXT NOT NULL,
                description TEXT,
                applied INTEGER DEFAULT 0,
                payload TEXT
            )
        """)

        # Tag history for reporting
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tag_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_ref TEXT NOT NULL,
                tag TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
        """)

        # Normalized targets for scheduled scans, used by reverse lookup.
        # Repopulated each time scheduled scans are refreshed.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_scan_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_value TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
        """)

        # Indexes for faster queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scans_ref ON scans(ref)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scans_fetched ON scans(fetched_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_staged_ref ON staged_changes(scan_ref)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_id ON scheduled_scans(scan_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags_tag ON tag_usage(tag)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sst_lookup ON scheduled_scan_targets(target_type, target_value)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sst_scan_id ON scheduled_scan_targets(scan_id)")
        
        # Run migrations for existing databases
        self._run_migrations(cursor)
        
        self.conn.commit()
        logger.debug(f"Database initialized: {self.db_path}")
    
    def _run_migrations(self, cursor) -> None:
        """
        Run schema migrations for existing databases.
        
        This ensures databases created before new columns were added
        get updated automatically.
        """
        # Check if scan_type column exists in staged_changes
        cursor.execute("PRAGMA table_info(staged_changes)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'scan_type' not in columns:
            logger.info("Migrating database: adding scan_type column to staged_changes")
            cursor.execute("""
                ALTER TABLE staged_changes
                ADD COLUMN scan_type TEXT DEFAULT 'scan'
            """)
            logger.info("Migration complete: scan_type column added")

        if 'payload' not in columns:
            logger.info("Migrating database: adding payload column to staged_changes")
            cursor.execute("""
                ALTER TABLE staged_changes
                ADD COLUMN payload TEXT
            """)
            logger.info("Migration complete: payload column added")
    
    # ========================================================
    # SCAN STORAGE
    # ========================================================
    
    def save_scans(self, scans: List[Dict[str, Any]]) -> int:
        """
        Save a batch of scans as a point-in-time snapshot.
        
        Returns:
            Number of scans saved
        """
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()
        count = 0
        
        for scan in scans:
            tags = scan.get("tags", [])
            if isinstance(tags, str):
                tags = [tags] if tags else []
            
            try:
                cursor.execute("""
                    INSERT INTO scans 
                    (ref, title, target, status, scan_type, option_profile, 
                     launched, duration, tags, raw_data, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    scan.get("ref", ""),
                    scan.get("title", ""),
                    scan.get("target", ""),
                    scan.get("status", ""),
                    scan.get("type", ""),
                    scan.get("option_profile", ""),
                    scan.get("launched", ""),
                    scan.get("duration", ""),
                    json.dumps(tags),
                    json.dumps(scan),
                    now,
                ))
                count += 1
                
                # Also record tag usage
                for tag in tags:
                    cursor.execute("""
                        INSERT INTO tag_usage (scan_ref, tag, recorded_at)
                        VALUES (?, ?, ?)
                    """, (scan.get("ref", ""), tag, now))
                    
            except sqlite3.IntegrityError:
                logger.debug(f"Scan {scan.get('ref')} already exists for {now}")
        
        self.conn.commit()
        logger.info(f"Saved {count} scans to database")
        return count
    
    def get_latest_scans(self) -> List[ScanRecord]:
        """Get the most recent snapshot of all scans."""
        cursor = self.conn.cursor()
        
        # Get the latest fetch time
        cursor.execute("SELECT MAX(fetched_at) FROM scans")
        row = cursor.fetchone()
        if not row or not row[0]:
            return []
        
        latest_time = row[0]
        
        cursor.execute("""
            SELECT ref, title, target, status, scan_type, option_profile,
                   launched, duration, tags, raw_data, fetched_at
            FROM scans
            WHERE fetched_at = ?
            ORDER BY launched DESC
        """, (latest_time,))
        
        return [ScanRecord(*row) for row in cursor.fetchall()]
    
    def get_scan_history(self, scan_ref: str, limit: int = 10) -> List[ScanRecord]:
        """Get historical snapshots for a specific scan."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT ref, title, target, status, scan_type, option_profile,
                   launched, duration, tags, raw_data, fetched_at
            FROM scans
            WHERE ref = ?
            ORDER BY fetched_at DESC
            LIMIT ?
        """, (scan_ref, limit))
        
        return [ScanRecord(*row) for row in cursor.fetchall()]
    
    # ========================================================
    # SCHEDULED SCAN STORAGE
    # ========================================================
    
    def save_scheduled_scans(self, scans: List[Dict[str, Any]]) -> int:
        """
        Save scheduled scans as a point-in-time snapshot.

        Also rewrites scheduled_scan_targets so reverse-lookup queries
        always reflect the latest refresh.

        Returns:
            Number of scheduled scans saved
        """
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()
        count = 0

        # Clear and repopulate the targets index for the new snapshot
        cursor.execute("DELETE FROM scheduled_scan_targets")

        for scan in scans:
            try:
                cursor.execute("""
                    INSERT INTO scheduled_scans
                    (scan_id, title, target, active, option_profile, scanner,
                     schedule, next_launch, last_launch, owner, raw_data, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    scan.get("id", ""),
                    scan.get("title", ""),
                    scan.get("target", ""),
                    1 if scan.get("active") else 0,
                    scan.get("option_profile", ""),
                    scan.get("scanner", ""),
                    scan.get("schedule", ""),
                    scan.get("next_launch", ""),
                    scan.get("last_launch", ""),
                    scan.get("owner", ""),
                    json.dumps(scan),
                    now,
                ))
                count += 1

                # Index normalized targets for reverse lookup
                scan_id = scan.get("id", "")
                for tgt in scan.get("targets", []) or []:
                    cursor.execute("""
                        INSERT INTO scheduled_scan_targets
                        (scan_id, target_type, target_value, fetched_at)
                        VALUES (?, ?, ?, ?)
                    """, (scan_id, tgt.get("type", ""), tgt.get("value", ""), now))

            except sqlite3.IntegrityError:
                logger.debug(f"Scheduled scan {scan.get('id')} already exists for {now}")

        self.conn.commit()
        logger.info(f"Saved {count} scheduled scans to database")
        return count

    def find_scans_by_target(
        self, target_type: str, target_value: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Find all scans (scheduled + recent) that include a given target.

        Args:
            target_type: 'ip' | 'range' | 'asset_group' | 'tag' | 'ip_list'
            target_value: literal value to match

        Returns:
            {'scheduled': [...], 'recent': [...]}
        """
        cursor = self.conn.cursor()

        # --- scheduled scans: indexed lookup on scheduled_scan_targets ---
        scheduled: List[Dict[str, Any]] = []
        if target_type in ("ip", "range"):
            # IP-in-CIDR/range membership: pull all ip/range targets and
            # check membership in Python (small N, fast enough)
            cursor.execute("""
                SELECT DISTINCT t.scan_id, t.target_type, t.target_value, s.title
                FROM scheduled_scan_targets t
                LEFT JOIN scheduled_scans s ON s.scan_id = t.scan_id
                WHERE t.target_type IN ('ip', 'range')
            """)
            try:
                import ipaddress
                needle = ipaddress.ip_address(target_value)
            except (ValueError, ImportError):
                needle = None

            for row in cursor.fetchall():
                hit = False
                stored = row["target_value"]
                if stored == target_value:
                    hit = True
                elif needle is not None:
                    try:
                        if "-" in stored:
                            start, end = [ipaddress.ip_address(p.strip()) for p in stored.split("-", 1)]
                            hit = start <= needle <= end
                        elif "/" in stored:
                            hit = needle in ipaddress.ip_network(stored, strict=False)
                    except ValueError:
                        pass
                if hit:
                    scheduled.append({
                        "scan_id": row["scan_id"],
                        "title": row["title"],
                        "matched_target": f"{row['target_type']}:{stored}",
                    })
        else:
            cursor.execute("""
                SELECT DISTINCT t.scan_id, s.title, t.target_value
                FROM scheduled_scan_targets t
                LEFT JOIN scheduled_scans s ON s.scan_id = t.scan_id
                WHERE t.target_type = ? AND t.target_value = ?
            """, (target_type, target_value))
            for row in cursor.fetchall():
                scheduled.append({
                    "scan_id": row["scan_id"],
                    "title": row["title"],
                    "matched_target": f"{target_type}:{row['target_value']}",
                })

        # --- recent (running) scans: LIKE search against scans.target ---
        # Only meaningful for IP / asset_group / tag literal text
        recent: List[Dict[str, Any]] = []
        cursor.execute("SELECT MAX(fetched_at) FROM scans")
        row = cursor.fetchone()
        if row and row[0]:
            latest = row[0]
            cursor.execute("""
                SELECT ref, title, target
                FROM scans
                WHERE fetched_at = ? AND target LIKE ?
            """, (latest, f"%{target_value}%"))
            for r in cursor.fetchall():
                recent.append({
                    "ref": r["ref"],
                    "title": r["title"],
                    "matched_target": r["target"],
                })

        return {"scheduled": scheduled, "recent": recent}
    
    def get_latest_scheduled_scans(self) -> List[Dict[str, Any]]:
        """Get the most recent snapshot of all scheduled scans."""
        cursor = self.conn.cursor()
        
        # Get the latest fetch time
        cursor.execute("SELECT MAX(fetched_at) FROM scheduled_scans")
        row = cursor.fetchone()
        if not row or not row[0]:
            return []
        
        latest_time = row[0]
        
        cursor.execute("""
            SELECT scan_id, title, target, active, option_profile, scanner,
                   schedule, next_launch, last_launch, owner, fetched_at
            FROM scheduled_scans
            WHERE fetched_at = ?
            ORDER BY next_launch ASC
        """, (latest_time,))
        
        return [
            {
                "id": row["scan_id"],
                "title": row["title"],
                "target": row["target"],
                "active": bool(row["active"]),
                "option_profile": row["option_profile"],
                "scanner": row["scanner"],
                "schedule": row["schedule"],
                "next_launch": row["next_launch"],
                "last_launch": row["last_launch"],
                "owner": row["owner"],
                "fetched_at": row["fetched_at"],
                "type": "scheduled",
            }
            for row in cursor.fetchall()
        ]
    
    # ========================================================
    # STAGING AREA
    # ========================================================
    
    def stage_change(
        self,
        scan_ref: str,
        change_type: ChangeType,
        old_value: str = "",
        new_value: str = "",
        description: str = "",
        scan_type: str = "scan",
        payload: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Stage a change for review before applying.

        Args:
            scan_ref: Scan reference ID or scheduled scan ID. For CREATE/LAUNCH
                actions where there is no existing ref, pass the proposed title.
            change_type: Type of change (pause, resume, activate, create, ...)
            old_value: Previous value (for display)
            new_value: New value (for display)
            description: Human-readable description
            scan_type: 'scan' for running scans, 'scheduled' for scheduled scans
            payload: Optional dict serialized to JSON for CREATE/MODIFY/LAUNCH
                actions where the full configuration must be carried.

        Returns:
            ID of the staged change
        """
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()
        payload_json = json.dumps(payload) if payload is not None else None

        cursor.execute("""
            INSERT INTO staged_changes
            (scan_ref, scan_type, change_type, old_value, new_value, staged_at, description, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (scan_ref, scan_type, change_type.value, old_value, new_value, now, description, payload_json))

        self.conn.commit()
        change_id = cursor.lastrowid
        logger.info(f"Staged change {change_id}: {change_type.value} on {scan_type}/{scan_ref}")
        return change_id

    def get_staged_changes(self, pending_only: bool = True) -> List[StagedChange]:
        """Get all staged changes."""
        cursor = self.conn.cursor()

        if pending_only:
            cursor.execute("""
                SELECT id, scan_ref, COALESCE(scan_type, 'scan') as scan_type,
                       change_type, old_value, new_value,
                       staged_at, description, applied, payload
                FROM staged_changes
                WHERE applied = 0
                ORDER BY staged_at DESC
            """)
        else:
            cursor.execute("""
                SELECT id, scan_ref, COALESCE(scan_type, 'scan') as scan_type,
                       change_type, old_value, new_value,
                       staged_at, description, applied, payload
                FROM staged_changes
                ORDER BY staged_at DESC
            """)

        return [StagedChange(*row) for row in cursor.fetchall()]
    
    def mark_change_applied(self, change_id: int) -> None:
        """Mark a staged change as applied."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE staged_changes SET applied = 1 WHERE id = ?",
            (change_id,)
        )
        self.conn.commit()
        logger.info(f"Marked change {change_id} as applied")
    
    def clear_staged_change(self, change_id: int) -> None:
        """Remove a staged change (discard)."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM staged_changes WHERE id = ?", (change_id,))
        self.conn.commit()
        logger.info(f"Cleared staged change {change_id}")
    
    def clear_all_staged(self) -> int:
        """Clear all pending staged changes."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM staged_changes WHERE applied = 0")
        count = cursor.rowcount
        self.conn.commit()
        logger.info(f"Cleared {count} staged changes")
        return count
    
    # ========================================================
    # DIFF COMPARISON
    # ========================================================
    
    def get_diff(self, scan_ref: str) -> Dict[str, Any]:
        """
        Compare staged changes against current state.
        
        Returns:
            Dict with 'current', 'staged', and 'changes' keys
        """
        # Get current state from latest snapshot
        history = self.get_scan_history(scan_ref, limit=1)
        current = asdict(history[0]) if history else {}
        
        # Get pending changes
        staged = [
            c for c in self.get_staged_changes(pending_only=True)
            if c.scan_ref == scan_ref
        ]
        
        return {
            "scan_ref": scan_ref,
            "current": current,
            "staged_changes": [
                {
                    "id": c.id,
                    "type": c.change_type,
                    "old": c.old_value,
                    "new": c.new_value,
                    "description": c.description,
                    "staged_at": c.staged_at,
                }
                for c in staged
            ],
            "has_changes": len(staged) > 0,
        }
    
    # ========================================================
    # TAG REPORTING
    # ========================================================
    
    def get_tag_report(self) -> List[Dict[str, Any]]:
        """
        Generate tag usage report.
        
        Returns:
            List of dicts with tag, count, and example scans
        """
        cursor = self.conn.cursor()
        
        # Get tag counts
        cursor.execute("""
            SELECT tag, COUNT(DISTINCT scan_ref) as scan_count
            FROM tag_usage
            GROUP BY tag
            ORDER BY scan_count DESC
        """)
        
        report = []
        for row in cursor.fetchall():
            tag = row["tag"]
            count = row["scan_count"]
            
            # Get example scans for this tag
            cursor.execute("""
                SELECT DISTINCT scan_ref 
                FROM tag_usage 
                WHERE tag = ?
                LIMIT 3
            """, (tag,))
            examples = [r["scan_ref"] for r in cursor.fetchall()]
            
            report.append({
                "tag": tag,
                "scan_count": count,
                "example_scans": examples,
            })
        
        return report
    
    def get_scans_by_tag(self, tag: str) -> List[str]:
        """Get all scan refs that have a specific tag."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT DISTINCT scan_ref
            FROM tag_usage
            WHERE tag = ?
        """, (tag,))
        return [row["scan_ref"] for row in cursor.fetchall()]
    
    def get_tag_timeline(self, tag: str) -> List[Dict[str, Any]]:
        """Get usage timeline for a specific tag."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT DATE(recorded_at) as date, COUNT(*) as count
            FROM tag_usage
            WHERE tag = ?
            GROUP BY DATE(recorded_at)
            ORDER BY date
        """, (tag,))
        return [{"date": row["date"], "count": row["count"]} for row in cursor.fetchall()]
    
    # ========================================================
    # UTILITIES
    # ========================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        cursor = self.conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM scans")
        total_snapshots = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(DISTINCT ref) FROM scans")
        unique_scans = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM staged_changes WHERE applied = 0")
        pending_changes = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(DISTINCT tag) FROM tag_usage")
        unique_tags = cursor.fetchone()[0]
        
        return {
            "total_snapshots": total_snapshots,
            "unique_scans": unique_scans,
            "pending_changes": pending_changes,
            "unique_tags": unique_tags,
            "db_path": str(self.db_path),
        }
    
    def close(self) -> None:
        """Close database connection for current thread."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
            logger.debug(f"Closed DB connection for thread {threading.current_thread().name}")


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.DEBUG)
    
    db = ScanDatabase("data/test.db")
    
    # Test save
    test_scans = [
        {
            "ref": "scan/123",
            "title": "Weekly Perimeter",
            "target": "10.0.0.0/24",
            "status": "Finished",
            "type": "Scheduled",
            "tags": ["perimeter", "weekly"],
        }
    ]
    db.save_scans(test_scans)
    
    # Test staging
    db.stage_change(
        "scan/123",
        ChangeType.PAUSE,
        description="Pausing for maintenance window"
    )
    
    # Test report
    print("\nTag Report:")
    for tag in db.get_tag_report():
        print(f"  {tag['tag']}: {tag['scan_count']} scans")
    
    print("\nStats:")
    print(db.get_stats())
    
    db.close()
