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
    ) -> requests.Response:
        """
        Make an authenticated API request.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            params: Query parameters
            data: POST data
            timeout: Request timeout in seconds (defaults to config.timeout)
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
                    timeout=request_timeout,
                )
            
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded")
            
            if response.status_code >= 400:
                raise QualysError(self._parse_error(response.text), response.status_code)
            
            return response
            
        except requests.Timeout:
            raise QualysError(f"Request timeout after {request_timeout}s: {endpoint}")
        except requests.RequestException as e:
            raise QualysError(f"Request failed: {e}")
    
    # SCAN OPERATIONS
    
    def list_scans(self, state: str = None, scan_type: str = None) -> List[Dict[str, Any]]:
        """List vulnerability scans."""
        params = {"action": "list"}
        if state:
            params["state"] = state
        if scan_type:
            params["type"] = scan_type
        
        response = self._request("GET", "/api/2.0/fo/scan/", params=params)
        return self._parse_scans(response.text)
    
    def get_scan(self, scan_ref: str) -> Dict[str, Any]:
        """Get details for a specific scan."""
        params = {"action": "list", "scan_ref": scan_ref, "show_status": 1}
        response = self._request("GET", "/api/2.0/fo/scan/", params=params)
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
        """List scan option profiles."""
        response = self._request(
            "GET", "/api/2.0/fo/subscription/option_profile/",
            params={"action": "list"}
        )
        return self._parse_profiles(response.text)
    
    def list_scheduled_scans(self) -> List[Dict[str, Any]]:
        """
        List scheduled scans (VM scan schedules).
        
        Uses a longer timeout (90s) as this API can be slow when there are
        many scheduled scans configured.
        
        API Endpoint: GET /api/2.0/fo/schedule/scan/?action=list
        Documentation: https://docs.qualys.com/en/vm/api/scans/vm_schedules/list_scan_schedules.htm
        """
        logger.info("Fetching scheduled scans from Qualys API...")
        
        response = self._request(
            "GET", "/api/2.0/fo/schedule/scan/",
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
                # Extract tags
                tags = []
                for tag_elem in elem.findall(".//TAG"):
                    tag_name = self._xml_text(tag_elem, "NAME")
                    if tag_name:
                        tags.append(tag_name)
                
                scans.append({
                    "ref": self._xml_text(elem, "REF"),
                    "title": self._xml_text(elem, "TITLE"),
                    "type": self._xml_text(elem, "TYPE"),
                    "status": self._xml_text(elem, "STATUS/STATE"),
                    "target": self._xml_text(elem, "TARGET"),
                    "launched": self._xml_text(elem, "LAUNCH_DATETIME"),
                    "duration": self._xml_text(elem, "DURATION"),
                    "option_profile": self._xml_text(elem, "OPTION_PROFILE/TITLE"),
                    "tags": tags,
                })
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
        profiles = []
        try:
            root = ET.fromstring(xml_text)
            for elem in root.findall(".//OPTION_PROFILE"):
                profiles.append({
                    "id": self._xml_text(elem, "BASIC_INFO/ID"),
                    "title": self._xml_text(elem, "BASIC_INFO/TITLE"),
                    "default": self._xml_text(elem, "BASIC_INFO/IS_DEFAULT"),
                })
        except ET.ParseError as e:
            logger.error(f"Failed to parse profile XML: {e}")
        return profiles
    
    def _parse_scheduled(self, xml_text: str) -> List[Dict[str, Any]]:
        """
        Parse scheduled scans from XML response.
        
        Expected XML structure (from Qualys API):
        <SCHEDULE_SCAN_LIST_OUTPUT>
          <RESPONSE>
            <SCHEDULE_SCAN_LIST>
              <SCAN>
                <ID>160642</ID>
                <ACTIVE>1</ACTIVE>
                <TITLE>My Daily Scan</TITLE>
                <USER_LOGIN>qualys_user</USER_LOGIN>
                <TARGET>10.10.10.10-10.10.10.20</TARGET>
                <ISCANNER_NAME>External Scanner</ISCANNER_NAME>
                <OPTION_PROFILE>
                  <TITLE>Initial Options</TITLE>
                </OPTION_PROFILE>
                <SCHEDULE>
                  <DAILY frequency_days="1" />
                  <NEXTLAUNCH_UTC>2017-12-02T00:30:00</NEXTLAUNCH_UTC>
                </SCHEDULE>
              </SCAN>
            </SCHEDULE_SCAN_LIST>
          </RESPONSE>
        </SCHEDULE_SCAN_LIST_OUTPUT>
        """
        scheduled = []
        try:
            # Log raw XML for debugging (first 1000 chars)
            logger.debug(f"Scheduled scan XML response (truncated): {xml_text[:1000]}")
            
            root = ET.fromstring(xml_text)
            
            # Check for error response
            error_text = self._xml_text(root, ".//TEXT")
            if error_text and "error" in error_text.lower():
                logger.error(f"API returned error: {error_text}")
                return []
            
            # Try multiple XPath patterns to find SCAN elements
            scan_elements = root.findall(".//SCHEDULE_SCAN_LIST/SCAN")
            
            if not scan_elements:
                # Fallback: try finding SCAN directly under RESPONSE
                scan_elements = root.findall(".//RESPONSE/SCHEDULE_SCAN_LIST/SCAN")
            
            if not scan_elements:
                # Second fallback: just find any SCAN element
                scan_elements = root.findall(".//SCAN")
                # Filter out non-scheduled scans (check for ID element which scheduled scans have)
                scan_elements = [e for e in scan_elements if e.find("ID") is not None and e.find("SCHEDULE") is not None]
            
            if not scan_elements:
                # Log the structure to help debug
                logger.warning(f"No scheduled scans found in response. Root tag: {root.tag}")
                for child in root:
                    logger.warning(f"  Child element: {child.tag}")
                    for grandchild in child:
                        logger.warning(f"    Grandchild: {grandchild.tag}")
                return []
            
            logger.info(f"Found {len(scan_elements)} SCAN elements in response")
            
            for elem in scan_elements:
                # Extract target - try multiple paths
                target = self._xml_text(elem, "TARGET")
                if not target:
                    # Try asset group
                    target = self._xml_text(elem, "ASSET_GROUP_TITLE_LIST/ASSET_GROUP_TITLE")
                if not target:
                    # Try asset tags
                    tag_include = self._xml_text(elem, "ASSET_TAGS/TAG_SET_INCLUDE")
                    if tag_include:
                        target = f"Tags: {tag_include}"
                
                # Extract schedule info - NEXTLAUNCH_UTC is inside SCHEDULE element
                schedule_elem = elem.find("SCHEDULE")
                schedule_text = ""
                next_launch = ""
                
                if schedule_elem is not None:
                    # Get next launch time
                    next_launch = self._xml_text(elem, "SCHEDULE/NEXTLAUNCH_UTC")
                    
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
                        schedule_text = f"Weekly ({weekdays})"
                    elif monthly is not None:
                        schedule_text = "Monthly"
                    else:
                        # Fallback - just indicate it's scheduled
                        start_hour = self._xml_text(elem, "SCHEDULE/START_HOUR")
                        start_min = self._xml_text(elem, "SCHEDULE/START_MINUTE")
                        if start_hour and start_min:
                            schedule_text = f"At {start_hour}:{start_min.zfill(2)}"
                
                # Get last launch from LASTLAUNCH_UTC if available
                last_launch = self._xml_text(elem, "LASTLAUNCH_UTC")
                if not last_launch:
                    last_launch = self._xml_text(elem, "SCHEDULE/LASTLAUNCH_UTC")
                
                scan_id = self._xml_text(elem, "ID")
                active_val = self._xml_text(elem, "ACTIVE")
                
                # ACTIVE can be "1", "0", or empty (empty means inactive)
                is_active = active_val == "1"
                
                scheduled.append({
                    "id": scan_id,
                    "title": self._xml_text(elem, "TITLE"),
                    "active": is_active,
                    "target": target or "N/A",
                    "option_profile": self._xml_text(elem, "OPTION_PROFILE/TITLE"),
                    "scanner": self._xml_text(elem, "ISCANNER_NAME"),
                    "schedule": schedule_text or "Scheduled",
                    "next_launch": next_launch,
                    "last_launch": last_launch,
                    "owner": self._xml_text(elem, "USER_LOGIN"),
                    "type": "scheduled",
                })
                
                logger.debug(f"Parsed scheduled scan: ID={scan_id}, Title={self._xml_text(elem, 'TITLE')}, Active={is_active}")
            
            logger.info(f"Successfully parsed {len(scheduled)} scheduled scans from API response")
            
        except ET.ParseError as e:
            logger.error(f"Failed to parse scheduled XML: {e}")
            logger.error(f"XML content (truncated): {xml_text[:2000]}")
        except Exception as e:
            logger.error(f"Unexpected error parsing scheduled scans: {e}")
            logger.error(f"XML content (truncated): {xml_text[:2000]}")
        
        return scheduled
    
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
