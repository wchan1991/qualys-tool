"""
Qualys API Client

Secure API client with:
- Session-based authentication
- Rate limiting
- SSL verification
- Private IP blocking
"""

import time
import logging
import ipaddress
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass
from enum import Enum
import xml.etree.ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config_loader import QualysConfig

logger = logging.getLogger(__name__)


class QualysError(Exception):
    """Base exception for Qualys API errors."""
    def __init__(self, message: str, status_code: int = None):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class AuthError(QualysError):
    """Authentication failed."""
    pass


class RateLimitError(QualysError):
    """Rate limit exceeded."""
    pass


class ScanStatus(Enum):
    RUNNING = "Running"
    FINISHED = "Finished"
    PAUSED = "Paused"
    CANCELED = "Canceled"
    ERROR = "Error"
    QUEUED = "Queued"


@dataclass
class RateLimiter:
    """Token bucket rate limiter."""
    calls_per_minute: int
    burst_limit: int = 10
    _tokens: float = None
    _last_update: float = None
    
    def __post_init__(self):
        self._tokens = float(self.burst_limit)
        self._last_update = time.time()
    
    def acquire(self) -> float:
        now = time.time()
        elapsed = now - self._last_update
        
        refill_rate = self.calls_per_minute / 60.0
        self._tokens = min(self.burst_limit, self._tokens + elapsed * refill_rate)
        self._last_update = now
        
        if self._tokens >= 1:
            self._tokens -= 1
            return 0.0
        
        wait_time = (1 - self._tokens) / refill_rate
        time.sleep(wait_time)
        self._tokens = 0
        self._last_update = time.time()
        return wait_time


# Blocked IP ranges
BLOCKED_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
]


def is_target_allowed(target: str, block_private: bool = True) -> bool:
    """Check if scan target is allowed."""
    if not block_private:
        return True
    
    try:
        network = ipaddress.ip_network(target, strict=False)
        for blocked in BLOCKED_RANGES:
            if network.overlaps(blocked):
                return False
        return True
    except ValueError:
        return True  # Hostname, allow


class QualysClient:
    """
    Secure Qualys API client.
    
    Usage:
        with QualysClient(config) as client:
            scans = client.list_scans()
    """
    
    def __init__(self, config: QualysConfig):
        self.config = config
        self._session: Optional[requests.Session] = None
        self._authenticated = False
        self._auth_expires: Optional[datetime] = None
        
        self._rate_limiter = None
        if config.rate_limit_enabled:
            self._rate_limiter = RateLimiter(calls_per_minute=config.calls_per_minute)
    
    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            
            retry = Retry(
                total=self.config.max_retries,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            adapter = HTTPAdapter(max_retries=retry)
            self._session.mount("https://", adapter)
            self._session.mount("http://", adapter)
            
            self._session.headers.update({
                "X-Requested-With": "QualysScanManager",
                "Accept": "application/xml",
            })
            self._session.verify = self.config.verify_ssl
        
        return self._session
    
    def _authenticate(self) -> None:
        if self._authenticated and self._auth_expires:
            if datetime.now() < self._auth_expires:
                return
        
        logger.info("Authenticating with Qualys API...")
        session = self._get_session()
        url = f"{self.config.api_url}/api/2.0/fo/session/"
        
        try:
            response = session.post(
                url,
                data={
                    "action": "login",
                    "username": self.config.username,
                    "password": self.config.password,
                },
                timeout=self.config.timeout,
            )
            
            if response.status_code == 200 and "logged in" in response.text.lower():
                self._authenticated = True
                self._auth_expires = datetime.now() + timedelta(hours=4)
                logger.info("Authentication successful")
            else:
                raise AuthError(f"Authentication failed: {self._parse_error(response.text)}")
                
        except requests.RequestException as e:
            raise AuthError(f"Authentication request failed: {e}")
    
    def _parse_error(self, xml_text: str) -> str:
        try:
            root = ET.fromstring(xml_text)
            for tag in ["TEXT", "MESSAGE", "ERROR"]:
                elem = root.find(f".//{tag}")
                if elem is not None and elem.text:
                    return elem.text
        except ET.ParseError:
            pass
        return xml_text[:200]
    
    def _request(
        self,
        method: str,
        endpoint: str,
        params: Dict = None,
        data: Dict = None,
        timeout: int = None,
        json_body: Any = None,
        headers: Dict[str, str] = None,
    ) -> requests.Response:
        """
        Make an authenticated API request.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            params: Query parameters
            data: POST form data
            timeout: Request timeout in seconds (defaults to config.timeout)
            json_body: Optional JSON body (for QPS endpoints).
                When set, sent as the request body in JSON form.
            headers: Optional per-request headers (merged with session headers).
        """
        if self._rate_limiter:
            self._rate_limiter.acquire()

        self._authenticate()

        session = self._get_session()
        url = f"{self.config.api_url}{endpoint}"
        request_timeout = timeout or self.config.timeout

        try:
            response = session.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json_body,
                headers=headers,
                timeout=request_timeout,
            )

            if response.status_code == 401:
                self._authenticated = False
                self._authenticate()
                response = session.request(
                    method=method,
                    url=url,
                    params=params,
                    data=data,
                    json=json_body,
                    headers=headers,
                    timeout=request_timeout,
                )
            
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded")
            
            if response.status_code >= 400:
                raise QualysError(self._parse_error(response.text), response.status_code)

            # Detect HTML responses (e.g. login redirects, captcha pages)
            ct = (response.headers.get("Content-Type") or "").lower()
            body_start = response.text.strip()[:50].lower()
            if "text/html" in ct or body_start.startswith("<!doctype") or body_start.startswith("<html"):
                raise QualysError(
                    "Qualys API returned an HTML page instead of XML/JSON. "
                    "This usually means a session redirect, CAPTCHA, or maintenance page. "
                    "Try logging into the Qualys portal manually first.",
                    response.status_code,
                )

            return response
            
        except requests.Timeout:
            raise QualysError(f"Request timeout after {request_timeout}s: {endpoint}")
        except requests.RequestException as e:
            raise QualysError(f"Request failed: {e}")
    
    # SCAN OPERATIONS
    
    def list_scans(self, state: str = None, scan_type: str = None) -> List[Dict[str, Any]]:
        """
        List vulnerability scans.

        API Endpoint: GET /api/3.0/fo/scan/?action=list
        v2.0 is EOL June 2026 (per Qualys API VM/PC User Guide v10.38.2).

        show_ags=1 / show_op=1 are required for Qualys to return asset-group
        and tag data in the <SCAN> payload; without these flags the XML
        omits <ASSET_GROUP_TITLE_LIST> and <TAG_LIST> entirely, which is
        why the tag report was coming back empty (F15).
        """
        params = {
            "action": "list",
            "show_ags": "1",
            "show_op": "1",
            "show_status": "1",
        }
        if state:
            params["state"] = state
        if scan_type:
            params["type"] = scan_type

        response = self._request("GET", "/api/3.0/fo/scan/", params=params)
        return self._parse_scans(response.text)

    def get_scan(self, scan_ref: str) -> Dict[str, Any]:
        """
        Get details for a specific scan.

        API Endpoint: GET /api/3.0/fo/scan/?action=list&scan_ref=...
        """
        params = {
            "action": "list",
            "scan_ref": scan_ref,
            "show_status": 1,
            "show_ags": "1",
            "show_op": "1",
        }
        response = self._request("GET", "/api/3.0/fo/scan/", params=params)
        scans = self._parse_scans(response.text)
        return scans[0] if scans else {}
    
    def pause_scan(self, scan_ref: str) -> bool:
        """Pause a running scan."""
        logger.info(f"Pausing scan: {scan_ref}")
        response = self._request(
            "POST", "/api/2.0/fo/scan/",
            data={"action": "pause", "scan_ref": scan_ref}
        )
        return "paused" in response.text.lower()
    
    def resume_scan(self, scan_ref: str) -> bool:
        """Resume a paused scan."""
        logger.info(f"Resuming scan: {scan_ref}")
        response = self._request(
            "POST", "/api/2.0/fo/scan/",
            data={"action": "resume", "scan_ref": scan_ref}
        )
        return "resumed" in response.text.lower()
    
    def cancel_scan(self, scan_ref: str) -> bool:
        """Cancel a scan."""
        logger.info(f"Canceling scan: {scan_ref}")
        response = self._request(
            "POST", "/api/2.0/fo/scan/",
            data={"action": "cancel", "scan_ref": scan_ref}
        )
        return "canceled" in response.text.lower()
    
    def list_scanners(self) -> List[Dict[str, Any]]:
        """List scanner appliances."""
        response = self._request("GET", "/api/2.0/fo/appliance/", params={"action": "list"})
        return self._parse_appliances(response.text)
    
    def list_option_profiles(self) -> List[Dict[str, Any]]:
        """
        List VM scan option profiles.

        API Endpoint: GET /api/4.0/fo/subscription/option_profile/vm/?action=list
        Latest VM-module version per Qualys API VM/PC User Guide v10.38.2.
        """
        response = self._request(
            "GET", "/api/4.0/fo/subscription/option_profile/vm/",
            params={"action": "list"}
        )
        return self._parse_profiles(response.text)
    
    def list_scheduled_scans(self) -> List[Dict[str, Any]]:
        """
        List scheduled scans (VM scan schedules).

        Uses a longer timeout (90s) as this API can be slow when there are
        many scheduled scans configured.

        API Endpoint: GET /api/5.0/fo/schedule/scan/?action=list
        v2.0/3.0/4.0 are EOL June 2026 per Qualys API VM/PC User Guide v10.38.2.
        v5.0 response adds richer time-zone info and a MODIFIED date field.
        """
        logger.info("Fetching scheduled scans from Qualys API...")

        response = self._request(
            "GET", "/api/5.0/fo/schedule/scan/",
            params={"action": "list"},
            timeout=90  # Longer timeout for scheduled scans
        )
        
        # Log response status and size for debugging
        logger.debug(f"Scheduled scans API response length: {len(response.text)} bytes")
        
        result = self._parse_scheduled(response.text)
        logger.info(f"Retrieved {len(result)} scheduled scans from Qualys")
        
        return result
    
    # XML PARSERS
    
    def _parse_scans(self, xml_text: str) -> List[Dict[str, Any]]:
        scans = []
        try:
            root = ET.fromstring(xml_text)
            for elem in root.findall(".//SCAN"):
                # Extract tags (F15): Qualys wraps tags in multiple
                # possible paths depending on show_ags/show_tags flags.
                tags = []
                # Primary path: <TAG_LIST><TAG><NAME>…</NAME></TAG></TAG_LIST>
                for tag_elem in elem.findall(".//TAG_LIST/TAG"):
                    tag_name = (
                        self._xml_text(tag_elem, "NAME")
                        or (tag_elem.text or "").strip()
                    )
                    if tag_name:
                        tags.append(tag_name)
                # Secondary path: <ASSET_TAGS><TAG_SET_INCLUDE><TAG>Name</TAG></TAG_SET_INCLUDE></ASSET_TAGS>
                if not tags:
                    for tag_elem in elem.findall(".//ASSET_TAGS/TAG_SET_INCLUDE/TAG"):
                        tag_name = (
                            self._xml_text(tag_elem, "NAME")
                            or (tag_elem.text or "").strip()
                        )
                        if tag_name:
                            tags.append(tag_name)
                # Fallback: any <TAG> descendant (older API flavours)
                if not tags:
                    for tag_elem in elem.findall(".//TAG"):
                        tag_name = (
                            self._xml_text(tag_elem, "NAME")
                            or (tag_elem.text or "").strip()
                        )
                        if tag_name:
                            tags.append(tag_name)

                # Asset-group list (separate from tags, shown when show_ags=1)
                asset_groups = []
                for ag in elem.findall(".//ASSET_GROUP_TITLE_LIST/ASSET_GROUP_TITLE"):
                    if ag.text and ag.text.strip():
                        asset_groups.append(ag.text.strip())

                # Host processing counts (nested under STATUS in Qualys XML)
                processed = self._xml_text(elem, "STATUS/PROCESSED") or self._xml_text(elem, ".//PROCESSED")
                total_hosts = self._xml_text(elem, "STATUS/TOTAL") or self._xml_text(elem, ".//TOTAL")

                scan_data = {
                    "ref": self._xml_text(elem, "REF"),
                    "title": self._xml_text(elem, "TITLE"),
                    "type": self._xml_text(elem, "TYPE"),
                    "status": self._xml_text(elem, "STATUS/STATE"),
                    "target": self._xml_text(elem, "TARGET"),
                    "launched": self._xml_text(elem, "LAUNCH_DATETIME"),
                    "duration": self._xml_text(elem, "DURATION"),
                    "option_profile": self._xml_text(elem, "OPTION_PROFILE/TITLE"),
                    "tags": tags,
                    "asset_groups": asset_groups,
                }

                # Add host counts when available
                if processed:
                    scan_data["processed"] = int(processed)
                if total_hosts:
                    scan_data["total_hosts"] = int(total_hosts)

                scans.append(scan_data)
        except ET.ParseError as e:
            logger.error(f"Failed to parse scan XML: {e}")
        return scans
    
    def _parse_appliances(self, xml_text: str) -> List[Dict[str, Any]]:
        appliances = []
        try:
            root = ET.fromstring(xml_text)
            for elem in root.findall(".//APPLIANCE"):
                appliances.append({
                    "id": self._xml_text(elem, "ID"),
                    "name": self._xml_text(elem, "NAME"),
                    "status": self._xml_text(elem, "STATUS"),
                    "type": self._xml_text(elem, "TYPE"),
                    "version": self._xml_text(elem, "SOFTWARE_VERSION"),
                })
        except ET.ParseError as e:
            logger.error(f"Failed to parse appliance XML: {e}")
        return appliances
    
    def _parse_profiles(self, xml_text: str) -> List[Dict[str, Any]]:
        """
        Parse VM option profiles from /api/4.0/fo/subscription/option_profile/vm/
        The profile name lives in BASIC_INFO/GROUP_NAME (TITLE is a legacy fallback).
        """
        profiles = []
        try:
            root = ET.fromstring(xml_text)
            for elem in root.findall(".//OPTION_PROFILE"):
                title = (
                    self._xml_text(elem, "BASIC_INFO/GROUP_NAME")
                    or self._xml_text(elem, "BASIC_INFO/TITLE")
                )
                profiles.append({
                    "id": self._xml_text(elem, "BASIC_INFO/ID"),
                    "title": title,
                    "default": self._xml_text(elem, "BASIC_INFO/IS_DEFAULT"),
                })
        except ET.ParseError as e:
            logger.error(f"Failed to parse profile XML: {e}")
        return profiles
    
    def _parse_scheduled(self, xml_text: str) -> List[Dict[str, Any]]:
        """
        Parse scheduled scans from XML response.
        
        Handles both API structures:
        1. V2 API: /api/2.0/fo/schedule/scan/?action=list
           Returns: SCHEDULE_SCAN_LIST_OUTPUT > RESPONSE > SCHEDULE_SCAN_LIST > SCAN
        
        2. Legacy check: Some responses may have different structures
        """
        scheduled = []
        
        # Log full XML for debugging (truncated for large responses)
        xml_preview = xml_text[:3000] if len(xml_text) > 3000 else xml_text
        logger.info(f"Parsing scheduled scan response ({len(xml_text)} bytes)")
        logger.debug(f"XML response:\n{xml_preview}")
        
        try:
            root = ET.fromstring(xml_text)
            logger.info(f"XML root element: <{root.tag}>")
            
            # Log immediate children of root
            for child in root:
                logger.debug(f"  Root child: <{child.tag}>")
            
            # Check for error response first
            error_elem = root.find(".//SIMPLE_RETURN")
            if error_elem is not None:
                error_text = self._xml_text(error_elem, "RESPONSE/TEXT")
                if error_text:
                    logger.error(f"API returned error response: {error_text}")
                    return []
            
            # Also check for error in CODE element
            code_elem = root.find(".//CODE")
            if code_elem is not None and code_elem.text:
                logger.error(f"API returned error code: {code_elem.text}")
                text_elem = root.find(".//TEXT")
                if text_elem is not None:
                    logger.error(f"Error message: {text_elem.text}")
                return []
            
            # Try to find SCAN elements using multiple strategies
            scan_elements = []
            
            # Strategy 1: Standard V2 API path
            scan_elements = root.findall(".//SCHEDULE_SCAN_LIST/SCAN")
            if scan_elements:
                logger.info(f"Found {len(scan_elements)} scans via SCHEDULE_SCAN_LIST/SCAN")
            
            # Strategy 2: Direct under RESPONSE
            if not scan_elements:
                scan_elements = root.findall(".//RESPONSE/SCHEDULE_SCAN_LIST/SCAN")
                if scan_elements:
                    logger.info(f"Found {len(scan_elements)} scans via RESPONSE/SCHEDULE_SCAN_LIST/SCAN")
            
            # Strategy 3: Any SCAN element with scheduling attributes
            if not scan_elements:
                all_scans = root.findall(".//SCAN")
                scan_elements = [e for e in all_scans if e.find("ID") is not None]
                if scan_elements:
                    logger.info(f"Found {len(scan_elements)} scans via generic .//SCAN search")
            
            # If still nothing, log the full structure for debugging
            if not scan_elements:
                logger.warning("No scheduled scan elements found. Logging XML structure:")
                self._log_xml_structure(root, indent=0)
                
                # Check if the response indicates no data
                datetime_elem = root.find(".//DATETIME")
                if datetime_elem is not None:
                    logger.info(f"Response timestamp: {datetime_elem.text}")
                    logger.warning("API responded successfully but returned no scheduled scans. "
                                   "This may indicate no scheduled scans exist or insufficient permissions.")
                return []
            
            # Parse each scan element
            for elem in scan_elements:
                try:
                    scan_data = self._parse_single_scheduled_scan(elem)
                    if scan_data:
                        scheduled.append(scan_data)
                        logger.debug(f"Parsed: ID={scan_data['id']}, Title={scan_data['title']}, Active={scan_data['active']}")
                except Exception as e:
                    logger.error(f"Error parsing individual scan element: {e}")
                    continue
            
            logger.info(f"Successfully parsed {len(scheduled)} scheduled scans")
            
        except ET.ParseError as e:
            logger.error(f"XML parsing failed: {e}")
            logger.error(f"Raw XML (first 2000 chars): {xml_text[:2000]}")
        except Exception as e:
            logger.error(f"Unexpected error in _parse_scheduled: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        return scheduled
    
    def _parse_single_scheduled_scan(self, elem) -> Dict[str, Any]:
        """Parse a single SCAN element into a dictionary."""
        # Collect a normalized target list. Each entry: {type, value}.
        # type ∈ {"ip", "range", "asset_group", "tag", "ip_list"}
        targets: List[Dict[str, str]] = []

        raw_target = self._xml_text(elem, "TARGET")
        if raw_target:
            for token in [t.strip() for t in raw_target.replace("\n", ",").split(",") if t.strip()]:
                ttype = "range" if "-" in token else "ip"
                targets.append({"type": ttype, "value": token})

        for ag in elem.findall("ASSET_GROUP_TITLE_LIST/ASSET_GROUP_TITLE"):
            if ag.text and ag.text.strip():
                targets.append({"type": "asset_group", "value": ag.text.strip()})

        for tag in elem.findall("ASSET_TAGS/TAG_SET_INCLUDE/TAG"):
            tag_name = (tag.text or "").strip()
            if tag_name:
                targets.append({"type": "tag", "value": tag_name})
        # Some responses inline tag names as a comma list
        tag_include_csv = self._xml_text(elem, "ASSET_TAGS/TAG_SET_INCLUDE")
        if tag_include_csv and not any(t["type"] == "tag" for t in targets):
            for name in [t.strip() for t in tag_include_csv.split(",") if t.strip()]:
                targets.append({"type": "tag", "value": name})

        for rng in elem.findall("USER_ENTERED_IPS/RANGE"):
            start = self._xml_text(rng, "START")
            end = self._xml_text(rng, "END")
            if start:
                value = f"{start}-{end}" if end and end != start else start
                targets.append({"type": "range" if end and end != start else "ip", "value": value})

        for ipl in elem.findall("IP_LIST_TITLE_LIST/IP_LIST_TITLE"):
            if ipl.text and ipl.text.strip():
                targets.append({"type": "ip_list", "value": ipl.text.strip()})

        # Build a friendly display string for the existing UI columns
        if targets:
            grouped: Dict[str, List[str]] = {}
            for t in targets:
                grouped.setdefault(t["type"], []).append(t["value"])
            parts = []
            for ttype in ("ip", "range", "asset_group", "tag", "ip_list"):
                if ttype in grouped:
                    label = {"ip": "", "range": "", "asset_group": "AG", "tag": "Tags", "ip_list": "IPList"}[ttype]
                    joined = ", ".join(grouped[ttype])
                    parts.append(f"{label}: {joined}" if label else joined)
            target = "; ".join(parts)
        else:
            target = ""
        
        # Extract schedule info
        schedule_elem = elem.find("SCHEDULE")
        schedule_text = ""
        next_launch = ""
        
        if schedule_elem is not None:
            # Get next launch time (try multiple paths)
            next_launch = self._xml_text(elem, "SCHEDULE/NEXTLAUNCH_UTC")
            if not next_launch:
                next_launch = self._xml_text(elem, "NEXTLAUNCH_UTC")
            
            # Build human-readable schedule description
            daily = schedule_elem.find("DAILY")
            weekly = schedule_elem.find("WEEKLY")
            monthly = schedule_elem.find("MONTHLY")
            
            if daily is not None:
                freq = daily.get("frequency_days", "1")
                schedule_text = f"Daily (every {freq} day{'s' if freq != '1' else ''})"
            elif weekly is not None:
                freq = weekly.get("frequency_weeks", "1")
                weekdays = weekly.get("weekdays", "")
                schedule_text = f"Weekly ({weekdays})" if weekdays else f"Weekly (every {freq} week{'s' if freq != '1' else ''})"
            elif monthly is not None:
                schedule_text = "Monthly"
            else:
                start_hour = self._xml_text(elem, "SCHEDULE/START_HOUR")
                start_min = self._xml_text(elem, "SCHEDULE/START_MINUTE")
                if start_hour and start_min:
                    schedule_text = f"At {start_hour}:{start_min.zfill(2)}"
        else:
            # Try to get next launch from element directly (some API versions)
            next_launch = self._xml_text(elem, "NEXTLAUNCH_UTC")
        
        # Get last launch
        last_launch = self._xml_text(elem, "LASTLAUNCH_UTC")
        if not last_launch:
            last_launch = self._xml_text(elem, "SCHEDULE/LASTLAUNCH_UTC")
        
        # Get ID and active status
        scan_id = self._xml_text(elem, "ID")
        active_val = self._xml_text(elem, "ACTIVE")
        
        # ACTIVE can be "1", "0", "2", "3", or empty
        # 1 = active, 0 = deactivated, 2 = active not paused, 3 = paused
        # F21: derive a tri-state status ("active" / "paused" / "inactive").
        is_active = active_val in ("1", "2")
        if active_val in ("1", "2"):
            status_str = "active"
        elif active_val == "3":
            status_str = "paused"
            is_active = False  # paused is not "running the schedule"
        else:
            status_str = "inactive"
        
        # v5.0 fields: TIME_ZONE/TIME_ZONE_CODE, MODIFIED date
        time_zone_code = self._xml_text(elem, "SCHEDULE/TIME_ZONE/TIME_ZONE_CODE")
        time_zone_details = self._xml_text(elem, "SCHEDULE/TIME_ZONE/TIME_ZONE_DETAILS")
        modified = (
            self._xml_text(elem, "MODIFIED")
            or self._xml_text(elem, "MODIFIED_DATE")
        )

        # Surface tag names as a flat list so the tag report (F15) can
        # aggregate scheduled-scan tag usage alongside on-demand scans.
        scheduled_tags = [t["value"] for t in targets if t.get("type") == "tag"]

        return {
            "id": scan_id,
            "title": self._xml_text(elem, "TITLE"),
            "active": is_active,
            "status": status_str,  # F21 tri-state
            "target": target or "N/A",
            "targets": targets,  # normalized list for reverse lookup
            "tags": scheduled_tags,
            "option_profile": self._xml_text(elem, "OPTION_PROFILE/TITLE"),
            "scanner": self._xml_text(elem, "ISCANNER_NAME"),
            "schedule": schedule_text or "Scheduled",
            "next_launch": next_launch,
            "last_launch": last_launch,
            "owner": self._xml_text(elem, "USER_LOGIN"),
            "time_zone": time_zone_code,
            "time_zone_details": time_zone_details,
            "modified": modified,
            "type": "scheduled",
        }
    
    def _log_xml_structure(self, elem, indent=0) -> None:
        """Recursively log XML structure for debugging."""
        prefix = "  " * indent
        attrs = " ".join(f'{k}="{v}"' for k, v in elem.attrib.items())
        text = (elem.text or "").strip()[:50]
        
        if attrs:
            logger.warning(f"{prefix}<{elem.tag} {attrs}>{' ...' + text if text else ''}")
        else:
            logger.warning(f"{prefix}<{elem.tag}>{' ...' + text if text else ''}")
        
        # Only go 3 levels deep to avoid spam
        if indent < 3:
            for child in elem:
                self._log_xml_structure(child, indent + 1)
    
    # SCHEDULED SCAN OPERATIONS
    
    def activate_scheduled_scan(self, scan_id: str) -> bool:
        """Activate a scheduled scan."""
        logger.info(f"Activating scheduled scan: {scan_id}")
        response = self._request(
            "POST", "/api/2.0/fo/schedule/scan/",
            data={"action": "update", "id": scan_id, "active": "1"}
        )
        return "updated" in response.text.lower() or "success" in response.text.lower()
    
    def deactivate_scheduled_scan(self, scan_id: str) -> bool:
        """Deactivate a scheduled scan."""
        logger.info(f"Deactivating scheduled scan: {scan_id}")
        response = self._request(
            "POST", "/api/2.0/fo/schedule/scan/",
            data={"action": "update", "id": scan_id, "active": "0"}
        )
        return "updated" in response.text.lower() or "success" in response.text.lower()
    
    def delete_scheduled_scan(self, scan_id: str) -> bool:
        """Delete a scheduled scan."""
        logger.info(f"Deleting scheduled scan: {scan_id}")
        response = self._request(
            "POST", "/api/2.0/fo/schedule/scan/",
            data={"action": "delete", "id": scan_id}
        )
        return "deleted" in response.text.lower() or "success" in response.text.lower()

    # ============================================================
    # CREATE / EDIT / LAUNCH
    # ============================================================

    def _build_target_params(self, target_spec: Dict[str, Any]) -> Dict[str, str]:
        """
        Convert a unified target spec into Qualys form fields.

        target_spec: {"type": "ips"|"asset_groups"|"tags"|"ip_list", "value": ...}
        """
        ttype = (target_spec or {}).get("type", "")
        value = (target_spec or {}).get("value", "")

        if ttype == "ips":
            # value is a comma-separated string or list of IPs/ranges/CIDRs
            ip_str = ",".join(value) if isinstance(value, list) else str(value)
            return {"ip": ip_str}

        if ttype == "asset_groups":
            # value is a list of asset group titles (or comma string)
            ag_str = ",".join(value) if isinstance(value, list) else str(value)
            return {"asset_groups": ag_str}

        if ttype == "tags":
            # value is a list of tag names (or comma string)
            tag_str = ",".join(value) if isinstance(value, list) else str(value)
            return {
                "target_from": "tags",
                "tag_set_by": "name",
                "tag_include_selector": "any",
                "tag_set_include": tag_str,
            }

        if ttype == "ip_list":
            # IP lists are resolved to literal IPs upstream (we receive the
            # already-expanded IP string here as `value`).
            ip_str = ",".join(value) if isinstance(value, list) else str(value)
            return {"ip": ip_str}

        raise ValueError(f"Unknown target type: {ttype!r}")

    def _build_schedule_params(self, schedule: Dict[str, Any]) -> Dict[str, str]:
        """
        Convert a unified schedule dict into Qualys schedule/scan form fields.

        schedule: {
            "occurrence": "daily"|"weekly"|"monthly",
            "frequency_days": int (daily),
            "frequency_weeks": int (weekly),
            "weekdays": "monday,tuesday,..." (weekly),
            "day_of_month": int (monthly),
            "start_date": "YYYY-MM-DD",
            "start_hour": 0..23,
            "start_minute": 0..59,
            "time_zone_code": "US-PT" (etc.),
            "observe_dst": 0|1,
            "recurrence": int (0 = unlimited),
            "active": 0|1,
        }
        """
        if not schedule:
            return {}

        params: Dict[str, str] = {}
        occ = (schedule.get("occurrence") or "").lower()
        params["occurrence"] = occ

        if occ == "daily":
            params["frequency_days"] = str(schedule.get("frequency_days", 1))
        elif occ == "weekly":
            params["frequency_weeks"] = str(schedule.get("frequency_weeks", 1))
            if schedule.get("weekdays"):
                params["weekdays"] = str(schedule["weekdays"])
        elif occ == "monthly":
            if schedule.get("day_of_month") is not None:
                params["day_of_month"] = str(schedule["day_of_month"])
            params["frequency_months"] = str(schedule.get("frequency_months", 1))

        for src, dst in (
            ("start_date", "start_date"),
            ("start_hour", "start_hour"),
            ("start_minute", "start_minute"),
            ("time_zone_code", "time_zone_code"),
            ("observe_dst", "observe_dst"),
            ("recurrence", "recurrence"),
            ("active", "active"),
        ):
            if schedule.get(src) is not None:
                params[dst] = str(schedule[src])

        return params

    def _build_scan_form(
        self,
        payload: Dict[str, Any],
        action: str,
        include_schedule: bool = False,
    ) -> Dict[str, str]:
        """
        Compose the form-data dict for launch_scan / create_scheduled_scan /
        update_scheduled_scan from a unified payload.

        payload keys (all optional unless noted):
            scan_title (required for create/launch)
            option_id OR option_title (one required)
            iscanner_id OR iscanner_name (one usually required)
            target: {type, value}  (required for create/launch)
            ip_network_id
            priority
            schedule: {...}  (only used when include_schedule=True)
        """
        form: Dict[str, str] = {"action": action}

        if payload.get("scan_title"):
            form["scan_title"] = str(payload["scan_title"])

        if payload.get("option_id"):
            form["option_id"] = str(payload["option_id"])
        elif payload.get("option_title"):
            form["option_title"] = str(payload["option_title"])

        if payload.get("iscanner_id"):
            form["iscanner_id"] = str(payload["iscanner_id"])
        elif payload.get("iscanner_name"):
            form["iscanner_name"] = str(payload["iscanner_name"])

        if payload.get("ip_network_id"):
            form["ip_network_id"] = str(payload["ip_network_id"])
        if payload.get("priority") is not None:
            form["priority"] = str(payload["priority"])

        if payload.get("target"):
            form.update(self._build_target_params(payload["target"]))

        if include_schedule and payload.get("schedule"):
            form.update(self._build_schedule_params(payload["schedule"]))

        return form

    def launch_scan(self, payload: Dict[str, Any]) -> Dict[str, str]:
        """
        Launch an on-demand VM scan.

        API: POST /api/2.0/fo/scan/?action=launch
        Returns: {"id": "...", "reference": "scan/..."} parsed from
        the SIMPLE_RETURN ITEM_LIST.
        """
        form = self._build_scan_form(payload, action="launch", include_schedule=False)
        if "scan_title" not in form:
            raise ValueError("launch_scan requires scan_title")
        if "option_id" not in form and "option_title" not in form:
            raise ValueError("launch_scan requires option_id or option_title")
        if "ip" not in form and "asset_groups" not in form and "target_from" not in form:
            raise ValueError("launch_scan requires a target (ips/asset_groups/tags)")

        logger.info(f"Launching scan: {form.get('scan_title')}")
        response = self._request("POST", "/api/2.0/fo/scan/", data=form)
        return self._parse_simple_return_items(response.text)

    def create_scheduled_scan(self, payload: Dict[str, Any]) -> Dict[str, str]:
        """
        Create a new scheduled VM scan.

        API: POST /api/2.0/fo/schedule/scan/?action=create
        Returns: {"id": "..."} parsed from the SIMPLE_RETURN ITEM_LIST.
        """
        form = self._build_scan_form(payload, action="create", include_schedule=True)
        if "scan_title" not in form:
            raise ValueError("create_scheduled_scan requires scan_title")
        if "occurrence" not in form:
            raise ValueError("create_scheduled_scan requires schedule.occurrence")

        logger.info(f"Creating scheduled scan: {form.get('scan_title')}")
        response = self._request("POST", "/api/2.0/fo/schedule/scan/", data=form)
        return self._parse_simple_return_items(response.text)

    def update_scheduled_scan(self, scan_id: str, payload: Dict[str, Any]) -> bool:
        """
        Update fields on an existing scheduled scan.

        API: POST /api/2.0/fo/schedule/scan/?action=update
        Only the fields present in `payload` are sent.
        """
        form = self._build_scan_form(payload, action="update", include_schedule=True)
        form["id"] = str(scan_id)

        logger.info(f"Updating scheduled scan {scan_id}: keys={list(form.keys())}")
        response = self._request("POST", "/api/2.0/fo/schedule/scan/", data=form)
        return "success" in response.text.lower() or "updated" in response.text.lower()

    def get_scheduled_scan(self, scan_id: str) -> Dict[str, Any]:
        """Fetch a single scheduled scan by ID using the v5.0 list endpoint."""
        response = self._request(
            "GET", "/api/5.0/fo/schedule/scan/",
            params={"action": "list", "id": str(scan_id)},
        )
        scans = self._parse_scheduled(response.text)
        return scans[0] if scans else {}

    def get_scan_detail(self, scan_ref: str) -> Dict[str, Any]:
        """Fetch full details for a running/completed scan."""
        params = {"action": "list", "scan_ref": scan_ref, "show_status": 1, "show_op": 1}
        response = self._request("GET", "/api/3.0/fo/scan/", params=params)
        scans = self._parse_scans(response.text)
        return scans[0] if scans else {}

    # ------------------------------------------------------------
    # Metadata fetchers used by the target / option pickers
    # ------------------------------------------------------------

    def list_asset_groups(self) -> List[Dict[str, str]]:
        """List asset groups (id + title + IP set)."""
        response = self._request(
            "GET", "/api/2.0/fo/asset/group/",
            params={"action": "list"},
        )
        return self._parse_asset_groups(response.text)

    def list_ip_lists(self) -> List[Dict[str, str]]:
        """
        List IP search/static lists.

        NOTE: Qualys does not expose a single canonical "IP list" API for the
        VM module — typically the entries the UI shows as "IP lists" come from
        the asset-group IP sets. This stub returns [] so the picker still
        renders; the form falls back to free-text IPs.
        """
        return []

    def list_tags(self) -> List[Dict[str, str]]:
        """
        List asset tags via the v2 JSON Tag API.

        API: POST /qps/rest/2.0/search/am/tag (JSON body)
        """
        try:
            response = self._request(
                "POST", "/qps/rest/2.0/search/am/tag",
                json_body={"ServiceRequest": {}},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            import json as _json
            data = _json.loads(response.text)
            tags = []
            for tag in (
                data.get("ServiceResponse", {}).get("data", []) or []
            ):
                t = tag.get("Tag", tag)
                tags.append({"id": str(t.get("id", "")), "name": t.get("name", "")})
            return tags
        except Exception as e:
            logger.warning(f"list_tags failed (returning empty): {e}")
            return []

    def _parse_asset_groups(self, xml_text: str) -> List[Dict[str, str]]:
        groups = []
        try:
            root = ET.fromstring(xml_text)
            for elem in root.findall(".//ASSET_GROUP"):
                groups.append({
                    "id": self._xml_text(elem, "ID"),
                    "title": (
                        self._xml_text(elem, "TITLE")
                        or self._xml_text(elem, "NAME")
                    ),
                })
        except ET.ParseError as e:
            logger.error(f"Failed to parse asset group XML: {e}")
        return groups

    def _parse_simple_return_items(self, xml_text: str) -> Dict[str, str]:
        """
        Parse a Qualys SIMPLE_RETURN ITEM_LIST into a {KEY: VALUE} dict.
        Used for launch / create responses that return ID + REFERENCE.
        """
        items: Dict[str, str] = {}
        try:
            root = ET.fromstring(xml_text)
            for item in root.findall(".//ITEM_LIST/ITEM"):
                key = (self._xml_text(item, "KEY") or "").lower()
                val = self._xml_text(item, "VALUE")
                if key:
                    items[key] = val
        except ET.ParseError as e:
            logger.error(f"Failed to parse SIMPLE_RETURN: {e}")
        return items

    @staticmethod
    def _xml_text(elem: ET.Element, path: str) -> str:
        child = elem.find(path)
        return child.text.strip() if child is not None and child.text else ""
    
    # CLEANUP
    
    def logout(self) -> None:
        if self._authenticated:
            try:
                self._request("POST", "/api/2.0/fo/session/", data={"action": "logout"})
            except QualysError:
                pass
            self._authenticated = False
    
    def close(self) -> None:
        self.logout()
        if self._session:
            self._session.close()
            self._session = None
    
    def __enter__(self) -> "QualysClient":
        return self
    
    def __exit__(self, *args) -> None:
        self.close()
