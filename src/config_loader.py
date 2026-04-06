"""
Configuration Loader

Securely loads settings from config/.config with environment variable overrides.
Credentials are masked in all output.
"""

import os
import stat
import logging
import warnings
from pathlib import Path
from configparser import ConfigParser
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class QualysConfig:
    """Configuration container with masked credentials."""
    
    # API
    api_url: str = "https://qualysapi.qualys.com"
    timeout: int = 30
    max_retries: int = 3
    
    # Credentials
    username: str = ""
    password: str = ""
    
    # Scanning
    default_scanner: str = ""
    default_option_profile: str = ""
    
    # Rate limiting
    rate_limit_enabled: bool = True
    calls_per_minute: int = 100
    
    # Security
    verify_ssl: bool = True
    block_private_ips: bool = True
    
    # Database
    db_path: str = "data/qualys_scans.db"
    
    # Logging
    log_level: str = "INFO"
    log_payloads: bool = False
    
    def __repr__(self) -> str:
        return (
            f"QualysConfig(api_url='{self.api_url}', "
            f"username='{'*' * len(self.username) if self.username else '<NOT SET>'}', "
            f"password='{'*' * 8 if self.password else '<NOT SET>'}')"
        )
    
    def is_configured(self) -> bool:
        return bool(self.username and self.password and self.api_url)
    
    def validate(self) -> List[str]:
        issues = []
        if not self.api_url:
            issues.append("API URL required")
        if not self.username:
            issues.append("Username required (config or QUALYS_USERNAME env)")
        if not self.password:
            issues.append("Password required (config or QUALYS_PASSWORD env)")
        if not self.api_url.startswith("https://"):
            issues.append("API URL must use HTTPS")
        if not self.verify_ssl:
            issues.append("WARNING: SSL verification disabled")
        return issues


def check_file_permissions(filepath: Path) -> None:
    """Warn if config file has insecure permissions."""
    if not filepath.exists():
        return
    
    # Skip on Windows (no chmod concept)
    if os.name == 'nt':
        return
    
    mode = filepath.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        warnings.warn(
            f"\n⚠️  Config '{filepath}' is readable by others.\n"
            f"   Run: chmod 600 {filepath}\n",
            SecurityWarning,
            stacklevel=3
        )


def load_config(config_path: Optional[Path] = None) -> QualysConfig:
    """
    Load configuration from file and environment.
    
    Priority: Environment variables > config file > defaults
    """
    # Find config directory
    if config_path:
        config_dir = config_path.parent
        config_file = config_path
    else:
        # Relative to src/ parent
        config_dir = Path(__file__).parent.parent / "config"
        config_file = config_dir / ".config"
    
    parser = ConfigParser()
    
    # Load example for defaults
    example = config_dir / ".config.example"
    if example.exists():
        parser.read(example)
    
    # Load user config
    if config_file.exists():
        check_file_permissions(config_file)
        parser.read(config_file)
    else:
        logger.warning(f"Config not found: {config_file}")
    
    def get_str(sec: str, key: str, default: str = "") -> str:
        """Get string value, stripping whitespace and surrounding quotes."""
        value = parser.get(sec, key, fallback=default).strip()
        # Remove surrounding quotes (single or double) that users may accidentally add
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        return value
    
    def get_int(sec: str, key: str, default: int) -> int:
        try:
            return parser.getint(sec, key, fallback=default)
        except ValueError:
            return default
    
    def get_bool(sec: str, key: str, default: bool) -> bool:
        try:
            return parser.getboolean(sec, key, fallback=default)
        except ValueError:
            return default
    
    config = QualysConfig(
        api_url=get_str("api", "base_url", "https://qualysapi.qualys.com"),
        timeout=get_int("api", "timeout", 30),
        max_retries=get_int("api", "max_retries", 3),
        username=get_str("credentials", "username", ""),
        password=get_str("credentials", "password", ""),
        default_scanner=get_str("scanning", "default_scanner", ""),
        default_option_profile=get_str("scanning", "default_option_profile", ""),
        rate_limit_enabled=get_bool("rate_limit", "enabled", True),
        calls_per_minute=get_int("rate_limit", "calls_per_minute", 100),
        verify_ssl=get_bool("security", "verify_ssl", True),
        block_private_ips=get_bool("security", "block_private_ips", True),
        db_path=get_str("database", "db_path", "data/qualys_scans.db"),
        log_level=get_str("logging", "level", "INFO"),
        log_payloads=get_bool("logging", "log_payloads", False),
    )
    
    # Environment overrides
    env_map = {
        "QUALYS_USERNAME": ("username", str),
        "QUALYS_PASSWORD": ("password", str),
        "QUALYS_API_URL": ("api_url", str),
        "QUALYS_TIMEOUT": ("timeout", int),
        "QUALYS_VERIFY_SSL": ("verify_ssl", lambda x: x.lower() in ("true", "1", "yes")),
    }
    
    for env_var, (attr, converter) in env_map.items():
        value = os.environ.get(env_var)
        if value:
            setattr(config, attr, converter(value))
    
    return config


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    config = load_config()
    print(config)
    issues = config.validate()
    for issue in issues:
        print(f"  ❌ {issue}")
