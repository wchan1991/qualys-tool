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
        # `status` is the tri-state variant added in Wave 3 (F21): one of
        # "active", "paused", "inactive". The legacy `active` boolean is
        # kept for backward compatibility with older queries.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT NOT NULL,
                title TEXT,
                target TEXT,
                active INTEGER,
                status TEXT,
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

        if 'applied_at' not in columns:
            logger.info("Migrating database: adding applied_at column to staged_changes")
            cursor.execute("""
                ALTER TABLE staged_changes
                ADD COLUMN applied_at TEXT
            """)
            logger.info("Migration complete: applied_at column added")

        # F21: tri-state status column on scheduled_scans
        cursor.execute("PRAGMA table_info(scheduled_scans)")
        sched_cols = [row[1] for row in cursor.fetchall()]
        if 'status' not in sched_cols:
            logger.info("Migrating database: adding status column to scheduled_scans")
            cursor.execute("ALTER TABLE scheduled_scans ADD COLUMN status TEXT")
            cursor.execute("""
                UPDATE scheduled_scans
                   SET status = CASE WHEN active = 1 THEN 'active' ELSE 'inactive' END
                 WHERE status IS NULL
            """)
            logger.info("Migration complete: status column added and backfilled")
    
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
        now = datetime.now().astimezone().isoformat()
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
        now = datetime.now().astimezone().isoformat()
        count = 0

        # Clear and repopulate the targets index for the new snapshot
        cursor.execute("DELETE FROM scheduled_scan_targets")

        for scan in scans:
            try:
                status_value = scan.get("status") or (
                    "active" if scan.get("active") else "inactive"
                )
                cursor.execute("""
                    INSERT INTO scheduled_scans
                    (scan_id, title, target, active, status, option_profile, scanner,
                     schedule, next_launch, last_launch, owner, raw_data, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    scan.get("id", ""),
                    scan.get("title", ""),
                    scan.get("target", ""),
                    1 if scan.get("active") else 0,
                    status_value,
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

                # Record scheduled-scan tag usage so the tag report (F15)
                # aggregates both on-demand and scheduled populations.
                scheduled_tags = scan.get("tags", []) or []
                if isinstance(scheduled_tags, str):
                    scheduled_tags = [scheduled_tags] if scheduled_tags else []
                for tag in scheduled_tags:
                    cursor.execute("""
                        INSERT INTO tag_usage (scan_ref, tag, recorded_at)
                        VALUES (?, ?, ?)
                    """, (f"sched:{scan_id}", tag, now))

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
                         | 'option_profile' | 'scanner'
            target_value: literal value or CIDR to match

        Returns:
            {'scheduled': [...], 'recent': [...]}
        """
        import ipaddress as _ipmod
        cursor = self.conn.cursor()

        scheduled: List[Dict[str, Any]] = []
        recent: List[Dict[str, Any]] = []

        # F21 helper: derive tri-state status from row (prefers `status`
        # column, falls back to `active` boolean for pre-migration rows).
        def _sched_status(row):
            try:
                keys = row.keys() if hasattr(row, "keys") else []
                if "status" in keys and row["status"]:
                    return row["status"]
            except Exception:
                pass
            try:
                return "active" if bool(row["active"]) else "inactive"
            except Exception:
                return "inactive"

        # ── Option profile lookup (Features 5) ──────────────────────────
        if target_type == "option_profile":
            cursor.execute("SELECT MAX(fetched_at) FROM scheduled_scans")
            latest_sched = (cursor.fetchone() or [None])[0]
            if latest_sched:
                cursor.execute("""
                    SELECT DISTINCT scan_id, title, option_profile, owner, status, active, target
                    FROM scheduled_scans
                    WHERE fetched_at = ? AND LOWER(option_profile) LIKE LOWER(?)
                """, (latest_sched, f"%{target_value}%"))
                for row in cursor.fetchall():
                    scheduled.append({
                        "scan_id": row["scan_id"],
                        "title": row["title"],
                        "owner": row["owner"],
                        "status": _sched_status(row),
                        "active": bool(row["active"]),
                        "target": row["target"],
                        "matched_target": f"option_profile:{row['option_profile']}",
                    })

            cursor.execute("SELECT MAX(fetched_at) FROM scans")
            latest_scan = (cursor.fetchone() or [None])[0]
            if latest_scan:
                cursor.execute("""
                    SELECT ref, title, option_profile, status, target
                    FROM scans
                    WHERE fetched_at = ? AND LOWER(option_profile) LIKE LOWER(?)
                """, (latest_scan, f"%{target_value}%"))
                for r in cursor.fetchall():
                    recent.append({
                        "ref": r["ref"],
                        "title": r["title"],
                        "status": r["status"],
                        "owner": None,
                        "target": r["target"],
                        "matched_target": f"option_profile:{r['option_profile']}",
                    })
            return {"scheduled": scheduled, "recent": recent}

        # ── Scanner lookup (Feature 5) ───────────────────────────────────
        if target_type == "scanner":
            cursor.execute("SELECT MAX(fetched_at) FROM scheduled_scans")
            latest_sched = (cursor.fetchone() or [None])[0]
            if latest_sched:
                cursor.execute("""
                    SELECT DISTINCT scan_id, title, scanner, owner, status, active, target
                    FROM scheduled_scans
                    WHERE fetched_at = ? AND LOWER(scanner) LIKE LOWER(?)
                """, (latest_sched, f"%{target_value}%"))
                for row in cursor.fetchall():
                    scheduled.append({
                        "scan_id": row["scan_id"],
                        "title": row["title"],
                        "owner": row["owner"],
                        "status": _sched_status(row),
                        "active": bool(row["active"]),
                        "target": row["target"],
                        "matched_target": f"scanner:{row['scanner']}",
                    })
            # scans table has no scanner column — skip recent
            return {"scheduled": scheduled, "recent": recent}

        # ── IP / CIDR / range lookup (Feature 8) ────────────────────────
        if target_type in ("ip", "range"):
            needle_addr = None
            needle_net = None

            if "/" in target_value:
                try:
                    needle_net = _ipmod.ip_network(target_value, strict=False)
                except ValueError:
                    pass
            else:
                try:
                    needle_addr = _ipmod.ip_address(target_value)
                except ValueError:
                    pass

            cursor.execute("""
                SELECT DISTINCT t.scan_id, t.target_type, t.target_value,
                       s.title, s.active, s.status, s.target, s.owner
                FROM scheduled_scan_targets t
                LEFT JOIN scheduled_scans s ON s.scan_id = t.scan_id
                WHERE t.target_type IN ('ip', 'range')
            """)
            for row in cursor.fetchall():
                hit = False
                stored = row["target_value"] or ""

                if stored == target_value:
                    hit = True
                elif needle_addr is not None:
                    try:
                        if "-" in stored:
                            start, end = [_ipmod.ip_address(p.strip()) for p in stored.split("-", 1)]
                            hit = start <= needle_addr <= end
                        elif "/" in stored:
                            hit = needle_addr in _ipmod.ip_network(stored, strict=False)
                    except ValueError:
                        pass
                elif needle_net is not None:
                    try:
                        if "-" in stored:
                            start, end = [_ipmod.ip_address(p.strip()) for p in stored.split("-", 1)]
                            hit = (start in needle_net or end in needle_net or
                                   (start <= needle_net.network_address and
                                    end >= needle_net.broadcast_address))
                        elif "/" in stored:
                            hit = needle_net.overlaps(_ipmod.ip_network(stored, strict=False))
                        else:
                            hit = _ipmod.ip_address(stored) in needle_net
                    except ValueError:
                        pass

                if hit:
                    scheduled.append({
                        "scan_id": row["scan_id"],
                        "title": row["title"],
                        "active": bool(row["active"]),
                        "status": _sched_status(row),
                        "owner": row["owner"],
                        "target": row["target"],
                        "matched_target": f"{row['target_type']}:{stored}",
                    })

            # Recent scans — LIKE on target text
            # For CIDR searches use a prefix hint; for single IP use exact
            cursor.execute("SELECT MAX(fetched_at) FROM scans")
            latest_r = (cursor.fetchone() or [None])[0]
            if latest_r:
                if needle_net is not None:
                    # Derive prefix from first two octets for a fast LIKE hint
                    parts = str(needle_net.network_address).split(".")
                    like_hint = ".".join(parts[:2]) + "."
                else:
                    like_hint = target_value

                cursor.execute("""
                    SELECT ref, title, target, status
                    FROM scans
                    WHERE fetched_at = ? AND target LIKE ?
                """, (latest_r, f"%{like_hint}%"))
                for r in cursor.fetchall():
                    recent.append({
                        "ref": r["ref"],
                        "title": r["title"],
                        "status": r["status"],
                        "owner": None,
                        "target": r["target"],
                        "matched_target": r["target"],
                    })
            return {"scheduled": scheduled, "recent": recent}

        # ── Asset group / tag / ip_list exact match ──────────────────────
        cursor.execute("""
            SELECT DISTINCT t.scan_id, s.title, t.target_value, s.active, s.status, s.target, s.owner
            FROM scheduled_scan_targets t
            LEFT JOIN scheduled_scans s ON s.scan_id = t.scan_id
            WHERE t.target_type = ? AND t.target_value = ?
        """, (target_type, target_value))
        for row in cursor.fetchall():
            scheduled.append({
                "scan_id": row["scan_id"],
                "title": row["title"],
                "active": bool(row["active"]),
                "status": _sched_status(row),
                "owner": row["owner"],
                "target": row["target"],
                "matched_target": f"{target_type}:{row['target_value']}",
            })

        cursor.execute("SELECT MAX(fetched_at) FROM scans")
        latest_r = (cursor.fetchone() or [None])[0]
        if latest_r:
            cursor.execute("""
                SELECT ref, title, target, status
                FROM scans
                WHERE fetched_at = ? AND target LIKE ?
            """, (latest_r, f"%{target_value}%"))
            for r in cursor.fetchall():
                recent.append({
                    "ref": r["ref"],
                    "title": r["title"],
                    "status": r["status"],
                    "owner": None,
                    "target": r["target"],
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
            SELECT scan_id, title, target, active, status, option_profile, scanner,
                   schedule, next_launch, last_launch, owner, raw_data, fetched_at
            FROM scheduled_scans
            WHERE fetched_at = ?
            ORDER BY next_launch ASC
        """, (latest_time,))

        out = []
        for row in cursor.fetchall():
            keys = row.keys() if hasattr(row, "keys") else []
            status_val = row["status"] if "status" in keys else None
            if not status_val:
                status_val = "active" if bool(row["active"]) else "inactive"
            out.append({
                "id": row["scan_id"],
                "title": row["title"],
                "target": row["target"],
                "active": bool(row["active"]),
                "status": status_val,
                "option_profile": row["option_profile"],
                "scanner": row["scanner"],
                "schedule": row["schedule"],
                "next_launch": row["next_launch"],
                "last_launch": row["last_launch"],
                "owner": row["owner"],
                "raw_data": row["raw_data"] if "raw_data" in keys else None,
                "fetched_at": row["fetched_at"],
                "type": "scheduled",
            })
        return out
    
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
        now = datetime.now().astimezone().isoformat()
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
            "UPDATE staged_changes SET applied = 1, applied_at = ? WHERE id = ?",
            (datetime.now().isoformat(), change_id)
        )
        self.conn.commit()
        logger.info(f"Marked change {change_id} as applied")
    
    def get_changelog(self) -> List[Dict[str, Any]]:
        """Get all applied changes for the changelog."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, scan_ref, COALESCE(scan_type, 'scan') as scan_type,
                   change_type, old_value, new_value,
                   staged_at, description, applied_at
            FROM staged_changes
            WHERE applied = 1
            ORDER BY applied_at DESC, staged_at DESC
        """)
        return [
            {
                "id": row[0],
                "scan_ref": row[1],
                "scan_type": row[2],
                "action": row[3],
                "old_value": row[4],
                "new_value": row[5],
                "staged_at": row[6],
                "description": row[7],
                "applied_at": row[8] or row[6],
            }
            for row in cursor.fetchall()
        ]

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
    
    # ========================================================
    # STARTUP / BACKUP UTILITIES (Feature 1)
    # ========================================================

    def is_empty(self) -> bool:
        """Return True if the scans table has no rows (DB freshly cleared)."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM scans")
        return cursor.fetchone()[0] == 0

    def clear_scan_data(self) -> None:
        """
        Delete all scan/scheduled/tag data but preserve staged_changes.
        Called at startup after a backup has been made.
        """
        cursor = self.conn.cursor()
        for table in ("scans", "scheduled_scans", "tag_usage", "scheduled_scan_targets"):
            cursor.execute(f"DELETE FROM {table}")
        self.conn.commit()
        logger.info("Cleared scan data from database (staged_changes preserved)")

    # ========================================================
    # DASHBOARD TRAFFIC (Feature 6)
    # ========================================================

    def get_scan_traffic_24h(self) -> List[Dict[str, Any]]:
        """
        Return hourly scan launch counts for the last 24 hours.
        Returns list of 24 dicts: [{"hour": "HH:00", "count": N}, ...]
        """
        from datetime import datetime, timedelta

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT launched FROM scans
            WHERE fetched_at = (SELECT MAX(fetched_at) FROM scans)
              AND launched IS NOT NULL AND launched != ''
        """)
        rows = cursor.fetchall()

        now = datetime.now()
        cutoff = now - timedelta(hours=24)

        # Build 24 hourly buckets
        buckets: Dict[datetime, int] = {}
        for h in range(24):
            bucket_time = (cutoff + timedelta(hours=h)).replace(minute=0, second=0, microsecond=0)
            buckets[bucket_time] = 0

        for row in rows:
            launched_str = (row["launched"] or "").strip()
            if not launched_str:
                continue
            try:
                # Qualys format: "YYYY/MM/DD HH:MM:SS" (UTC) → normalise
                normalised = launched_str.replace("/", "-")
                # Append Z so JS/Python both treat it as UTC → local conversion
                if "+" not in normalised and normalised[-1] != "Z":
                    normalised += "Z"
                from dateutil.parser import parse as _parse
                dt = _parse(normalised).replace(tzinfo=None)  # naive local after conversion
            except Exception:
                continue

            if dt < cutoff:
                continue
            bucket = dt.replace(minute=0, second=0, microsecond=0)
            if bucket in buckets:
                buckets[bucket] += 1

        return [
            {"hour": k.strftime("%H:00"), "count": v}
            for k, v in sorted(buckets.items())
        ]

    # ========================================================
    # TOP TAGS (Feature 11)
    # ========================================================

    def get_top_tags(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the top N tags by distinct scan count, sorted descending."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT tag, COUNT(DISTINCT scan_ref) AS scan_count
            FROM tag_usage
            GROUP BY tag
            ORDER BY scan_count DESC
            LIMIT ?
        """, (limit,))
        return [{"tag": row["tag"], "count": row["scan_count"]} for row in cursor.fetchall()]

    def get_top_targets(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Return the most-used target strings across the latest snapshots of
        scheduled scans and on-demand scans (F17). Used to populate lookup
        chips so users can click to search common targets.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT target, COUNT(*) AS usage_count FROM (
                SELECT target FROM scheduled_scans
                 WHERE fetched_at = (SELECT MAX(fetched_at) FROM scheduled_scans)
                UNION ALL
                SELECT target FROM scans
                 WHERE fetched_at = (SELECT MAX(fetched_at) FROM scans)
            )
            WHERE target IS NOT NULL AND target != '' AND target != 'N/A'
            GROUP BY target
            ORDER BY usage_count DESC
            LIMIT ?
        """, (limit,))
        return [
            {"target": row["target"], "count": row["usage_count"]}
            for row in cursor.fetchall()
        ]

    def get_recent_scans(self, hours: int = 6) -> List[Dict[str, Any]]:
        """
        Return on-demand scans whose launched timestamp falls within the last
        `hours` window (F13). Reused by the Dashboard "Recent Scans (last 6h)"
        panel and by /api/scans/recent.
        """
        from datetime import datetime, timedelta, timezone
        try:
            from dateutil.parser import parse as _parse_dt
        except ImportError:
            _parse_dt = None

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT ref, title, target, status, scan_type, option_profile,
                   launched, duration, tags, raw_data, fetched_at
            FROM scans
            WHERE fetched_at = (SELECT MAX(fetched_at) FROM scans)
              AND launched IS NOT NULL AND launched != ''
            ORDER BY launched DESC
        """)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        out = []
        for row in cursor.fetchall():
            s = (row["launched"] or "").strip().replace("/", "-")
            if not s:
                continue
            if s[-1] not in "Zz" and "+" not in s[-6:]:
                s += "Z"
            try:
                dt = _parse_dt(s) if _parse_dt else datetime.fromisoformat(s.replace("Z", "+00:00"))
            except Exception:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                out.append({
                    "ref": row["ref"],
                    "title": row["title"],
                    "target": row["target"],
                    "status": row["status"],
                    "type": row["scan_type"],
                    "option_profile": row["option_profile"],
                    "launched": row["launched"],
                    "duration": row["duration"],
                    "tags": json.loads(row["tags"]) if row["tags"] else [],
                    "fetched_at": row["fetched_at"],
                })
        return out

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
