# Qualys Scan Manager

A browser-based tool for managing Qualys vulnerability scans with a staging workflow — review changes before applying them.

![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)
![Cross-platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

---

## What This Tool Does

- **Staging Workflow** — Stage changes for review before applying them to Qualys
- **Scheduled Scans** — View, create, edit, activate/deactivate, and delete recurring scans
- **Running Scans** — Monitor and control running scans (pause, resume, cancel)
- **Dashboard** — Unified metrics, activity charts, and scan forecasting
- **Calendar View** — Visualize scheduled scan launch times on a calendar
- **Target Lookup** — Reverse lookup to find scans targeting a specific IP or network
- **Scanner Inventory** — View available Qualys scanners
- **Tag Reporting** — See tag usage across all scans
- **Bulk Operations** — Stage actions on multiple scans at once
- **Backup/Restore** — Automatic database backups on startup with manual restore
- **Dark/Light Theme** — Toggle between themes (persisted in browser)

---

## Quick Start

### Step 1: Install Python

| OS | Instructions |
|----|--------------|
| **Windows** | Download from [python.org](https://www.python.org/downloads/). Check "Add to PATH" during install. |
| **macOS** | `brew install python` or download from [python.org](https://www.python.org/downloads/) |
| **Linux** | `sudo apt install python3 python3-pip` (Ubuntu/Debian) |

Verify:
```bash
python --version   # Should show 3.8 or higher
```

### Step 2: Install Dependencies

```bash
cd scannermanager
pip install -r requirements.txt
```

### Step 3: Configure Credentials

```bash
# Copy the example config
cp config/.config.example config/.config

# Edit with your credentials
# Windows: notepad config\.config
# macOS/Linux: nano config/.config
```

Edit the file:
```ini
[credentials]
username = your_qualys_username
password = your_qualys_password

[api]
base_url = https://qualysapi.qualys.com
```

> **Security tip (macOS/Linux):** Run `chmod 600 config/.config`

### Step 4: Run the Tool

```bash
python app.py
```

Open your browser: **http://localhost:5000**

On first launch, the app fetches scan data from Qualys before the full UI becomes available. You'll see a loading/init page until the initial refresh completes.

---

## Using the Tool

### Dashboard (`/`)
- Unified metrics for both scheduled and running scans
- Scan activity chart (past 24 hours) and forecast (next 24/48/72 hours)
- Pending staged changes counter
- Connection status indicator
- Click **Refresh All from Qualys** to fetch latest data

### Scheduled Scans (`/scheduled`)
- View all recurring scan schedules configured in Qualys
- See next launch time, schedule pattern, and active status
- **Activate** or **Deactivate** scheduled scans
- **Delete** scheduled scans (staged first for safety)
- Search and filter by title, target, or status
- Click any scan to view full details

### Running Scans (`/scans`)
- View scans that have run or are currently running
- **Pause**, **Resume**, or **Cancel** running scans
- Search and filter by status (Running, Paused, Queued, Finished)
- Click any scan to view full details

### Staging Page (`/staging`)
- Review **all** staged changes (both scheduled and running scans)
- Type badge shows whether the change applies to a scheduled or running scan
- Discard individual changes or all at once
- Click **Make It So** to apply all changes to Qualys

### Create/Edit Scans (`/scheduled/new`, `/scans/new`)
- Create new scheduled or on-demand scans
- Smart target picker with IP, CIDR, and hostname validation
- Select scanners and option profiles from your Qualys account
- Edit existing scheduled scans

### Calendar View (`/calendar`)
- Visual calendar of scheduled scan launch times
- Useful for spotting scheduling conflicts or gaps

### Target Lookup (`/lookup`)
- Reverse lookup — enter an IP, CIDR, or hostname
- Find all scans that include that target

### Scanner Inventory (`/scanners`)
- List all available Qualys scanners
- View scanner status and details

### Tags Page (`/tags`)
- See tag usage across all scans
- Useful for reporting on scan coverage

### Backup/Restore
- Database is automatically backed up on each app startup
- Restore from previous backups via the API

---

## The Staging Workflow

Works for **both** scheduled scans and running scans:

```
┌─────────────────┐     ┌──────────────┐     ┌──────────────┐
│  Scheduled or   │ ──> │ Stage Action │ ──> │   Review in  │
│  Running Scans  │     │ (with reason)│     │   Staging    │
└─────────────────┘     └──────────────┘     └──────────────┘
                                                    │
                                                    v
                                             ┌──────────────┐
                                             │ Make It So!  │
                                             └──────────────┘
```

**Supported Actions:**

| Scan Type | Actions Available |
|-----------|-------------------|
| **Scheduled** | Activate, Deactivate, Delete, Create, Modify |
| **Running** | Pause, Resume, Cancel |

**Why staging?** This prevents accidental changes. You can:
1. Stage multiple actions across different scan types
2. Review them all together in one place
3. Discard any you don't want
4. Apply them all at once

Bulk staging is also supported — select multiple scans and stage the same action on all of them.

---

## Project Structure

```
scannermanager/
├── app.py                  # Flask web application (run this)
├── cli.py                  # Command-line interface
├── requirements.txt        # Python dependencies
├── config/
│   ├── .config.example     # Template (copy to .config)
│   └── .config             # Your credentials (create this)
├── data/
│   └── qualys_scans.db     # Local SQLite database (auto-created)
├── src/
│   ├── api_client.py       # Qualys API client (auth, rate limiting, SSL)
│   ├── config_loader.py    # Config management with env var overrides
│   ├── database.py         # SQLite: scans, staging, tags
│   └── scan_manager.py     # Business logic layer
├── templates/              # 14 HTML templates (Jinja2)
│   ├── base.html           # Layout, navbar, theme toggle
│   ├── index.html          # Dashboard
│   ├── scans.html          # Running scans list
│   ├── scheduled.html      # Scheduled scans list
│   ├── staging.html        # Review staged changes
│   ├── scan_form.html      # Create/edit scan form
│   ├── calendar.html       # Calendar view
│   ├── target_lookup.html  # Reverse target lookup
│   ├── scanners.html       # Scanner inventory
│   ├── tags.html           # Tag report
│   └── ...                 # Detail pages, init, error
└── static/
    ├── style.css           # Responsive CSS, dark/light theme
    ├── app.js              # Main application logic
    └── target_picker.js    # Smart target input with validation
```

---

## Command Line (Optional)

A CLI is also available for headless operation:

```bash
python cli.py health      # Test API connection
python cli.py refresh     # Fetch scans from Qualys
python cli.py list        # List scans
python cli.py stage pause scan/123456789
python cli.py staged      # View staged changes
python cli.py apply       # Apply staged changes
python cli.py tags        # Tag report
```

---

## Configuration Reference

All settings go in `config/.config`. Environment variables override file values.

```ini
[credentials]
username =                      # Qualys username
password =                      # Qualys password

[api]
base_url = https://qualysapi.qualys.com   # See platform URLs below
timeout = 30                    # Request timeout in seconds
max_retries = 3                 # Retry count on failure

[scanning]
default_scanner =               # Default scanner appliance name
default_option_profile =        # Default option profile name

[rate_limit]
enabled = true                  # Enable API rate limiting
calls_per_minute = 100          # Max API calls per minute

[security]
verify_ssl = true               # Verify SSL certificates
block_private_ips = true        # Block scanning private IP ranges

[database]
db_path = data/qualys_scans.db  # Path to SQLite database

[logging]
level = INFO                    # Log level (DEBUG, INFO, WARNING, ERROR)
log_payloads = false            # Log raw API request/response bodies
```

**Environment variable overrides:**

| Variable | Overrides |
|----------|-----------|
| `QUALYS_USERNAME` | `[credentials] username` |
| `QUALYS_PASSWORD` | `[credentials] password` |
| `QUALYS_API_URL` | `[api] base_url` |
| `QUALYS_TIMEOUT` | `[api] timeout` |
| `QUALYS_VERIFY_SSL` | `[security] verify_ssl` |

Priority: Environment variables > config file > defaults

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'flask'"
```bash
pip install flask requests python-dateutil
```

### "Connection refused" or "Authentication failed"
1. Check credentials in `config/.config`
2. Verify API URL matches your Qualys platform:
   - US1: `https://qualysapi.qualys.com`
   - US2: `https://qualysapi.qg2.apps.qualys.com`
   - EU1: `https://qualysapi.qualys.eu`
   - EU2: `https://qualysguard.qualys.eu`

### "No connection adapters were found" error
Your API URL may have extra quotes. In `config/.config`, use:
```ini
# CORRECT:
base_url = https://qualysguard.qualys.eu

# WRONG (has quotes):
base_url = "https://qualysguard.qualys.eu"
```

### "Address already in use"
Another process is using port 5000. Either:
- Stop the other process
- Or edit `app.py` to use a different port

---

## Security Notes

- Credentials stored in `config/.config` — protect this file (`chmod 600` on macOS/Linux)
- SSL verification enabled by default
- API rate limiting enabled by default (100 calls/min)
- Private IP blocking enabled by default
- Local SQLite database — no data leaves your machine
- Web server only listens on localhost (127.0.0.1)
- Credentials are masked in all log output

---

## License

Internal tool — not for distribution.
