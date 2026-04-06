# Qualys Scan Manager

A browser-based tool for managing Qualys vulnerability scans with a staging workflow — review changes before applying them.

![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)
![Cross-platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

---

## What This Tool Does

- **📅 Scheduled Scans** — View, activate/deactivate, and manage recurring scan schedules
- **🔍 Recent Scans** — View completed/running scans with pause/resume/cancel controls
- **📋 Staging Workflow** — Stage changes for review before applying them
- **🚀 "Make It So" Button** — Apply all staged changes at once
- **🏷️ Tag Reporting** — See which tags are used across scans
- **📊 Dashboard** — Unified metrics for both scheduled and running scans
- **🌐 Browser-Based** — No desktop GUI dependencies

---

## Quick Start (5 minutes)

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
cd qualys-tool
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

---

## Using the Tool

### Dashboard
- View metrics for both **scheduled** and **recent** scans at a glance
- Shows pending staged changes count
- Click **🔄 Refresh All from Qualys** to fetch latest data

### 📅 Scheduled Scans (Primary Focus)
- View all recurring scan schedules configured in Qualys
- See next launch time, schedule pattern, active status
- **Activate** or **Deactivate** scheduled scans
- **Delete** scheduled scans (staged first for safety)
- Search and filter by title, target, or status

### 🔍 Recent Scans
- View scans that have run or are currently running
- **Pause**, **Resume**, or **Cancel** running scans
- Search and filter by status (Running, Paused, Queued, Finished)

### 📋 Staging Page
- Review **all** staged changes (both scheduled and recent scans)
- Type badge shows whether change applies to a scheduled or running scan
- Discard individual changes or all at once
- Click **🚀 Make It So** to apply all changes to Qualys

### 🏷️ Tags Page
- See tag usage across all scans
- Useful for reporting on scan coverage

---

## The Staging Workflow

Works for **both** scheduled scans and running scans:

```
┌─────────────────┐     ┌─────────────┐     ┌─────────────┐
│  Scheduled or   │ ──▶ │ Stage Action│ ──▶ │   Review    │
│  Recent Scans   │     │ (with reason│     │  in Staging │
└─────────────────┘     └─────────────┘     └─────────────┘
                                                   │
                                                   ▼
                                            ┌─────────────┐
                                            │ Make It So! │
                                            └─────────────┘
```

**Supported Actions:**

| Scan Type | Actions Available |
|-----------|-------------------|
| **Scheduled** | Activate, Deactivate, Delete |
| **Running** | Pause, Resume, Cancel |

**Why staging?** This prevents accidental changes. You can:
1. Stage multiple actions across different scan types
2. Review them all together in one place
3. Discard any you don't want
4. Apply them all at once

---

## Project Structure

```
qualys-tool/
├── app.py              # Flask web application (run this)
├── requirements.txt    # Python dependencies
├── config/
│   ├── .config.example # Template (copy to .config)
│   └── .config         # Your credentials (create this)
├── data/
│   └── qualys_scans.db # Local SQLite database (auto-created)
├── src/
│   ├── config_loader.py
│   ├── database.py     # SQLite: scans, staging, tags
│   ├── api_client.py   # Qualys API client
│   └── scan_manager.py # Business logic
├── templates/          # HTML templates
├── static/             # CSS and JavaScript
└── logs/               # Application logs
```

---

## Command Line (Optional)

A CLI is also available:

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

## Troubleshooting

### "ModuleNotFoundError: No module named 'flask'"
```bash
pip install flask requests
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

## Environment Variables (Optional)

Override config file settings:

```bash
export QUALYS_USERNAME="your_username"
export QUALYS_PASSWORD="your_password"
export QUALYS_API_URL="https://qualysapi.qualys.com"

python app.py
```

---

## Security Notes

- Credentials stored in `config/.config` — protect this file
- SSL verification enabled by default
- Local SQLite database — no data leaves your machine
- Web server only listens on localhost (127.0.0.1)

---

## License

Internal tool — not for distribution.
