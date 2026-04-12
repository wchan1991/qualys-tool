# Backlog

Changes and feature requests for the Qualys Scan Manager.

## How to Use

1. Add a new entry under **Proposed** using the template below
2. Ask Claude to review the backlog and discuss
3. Once agreed, Claude moves the item to **Approved** and implements it
4. After implementation and verification, Claude moves it to **Done**

### Entry Template

```markdown
### [REQ-XXX] Short title
- **Type:** Feature | Bug | Enhancement | Refactor
- **Priority:** High | Medium | Low
- **Description:** What needs to change and why
- **Acceptance Criteria:** How we know it's done
```

---

## Proposed

<!-- Add new requests here -->
### [REQ-013] Expansion 
- **Type:** Feature
- **Priority:** High
- **Description:** Add in an import scan as a sub menu for the Scheduled Scans. I want to be able to import existing excel sheets of planned scans, have the platforma assess the changes, have the ability to make changes in the tool and  publish.
- **Acceptance Criteria:** The acceptance criteria should be an existing submenu, the succesful interpretation of an excel sheet, seeing a single view of all the "scans" inside the sheet, setting accurate time and targets, and being able to control and publish.

### [REQ-018] Operator Notes for Scans
- **Type:** Feature
- **Priority:** Medium
- **Description:** Add a note/annotation function that lets operators track what each scan does and why. Local-only `scan_notes` SQLite table with full CRUD — any scan (on-demand or scheduled) can have multiple timestamped notes. Display as "Operator Notes" section in scan detail pages with textarea input and note history.
- **Acceptance Criteria:** Notes can be created, viewed, and deleted per scan. Notes persist across refreshes (local DB). Notes visible on scan detail and scheduled scan detail pages.

## Approved

<!-- Items approved for implementation -->

## In Progress

<!-- Items currently being worked on -->

<!-- REQ-008 and REQ-009 moved to Done -->

## Done

### [REQ-001] Improve non-scheduled scans table formatting
- **Type:** Enhancement
- **Priority:** Medium
- **Completed:** 2026-04-11
- **Summary:** Changed scans and staging tables from `.table` to `.data-table` class for consistent styling (rounded corners, shadow, hover states). Added `.target-cell` class to target column.

### [REQ-002] Bulk action support for non-scheduled scans
- **Type:** Feature
- **Priority:** High
- **Completed:** 2026-04-11
- **Summary:** Already implemented — checkboxes, select all, bulk bar (Pause/Resume/Cancel), and `/api/stage/bulk` endpoint were all in place.

### [REQ-003] Backup management and offline mode
- **Type:** Feature
- **Priority:** High
- **Completed:** 2026-04-11
- **Summary:**
  - Backups moved to top-level `backups/` folder, auto-pruned to keep only 2 most recent, excluded from git via `.gitignore`
  - Offline mode auto-detects when Qualys API is unreachable at startup; preserves cached data, shows warning banner, disables "Make It So" button, blocks `/api/apply` endpoint. Staging still works locally.

### [REQ-004] Edit support for all scan types and prefill existing values
- **Type:** Enhancement
- **Priority:** High
- **Completed:** 2026-04-11
- **Summary:**
  - Added `edit_scan` mode — non-scheduled scans now have an Edit button on the detail page that opens the launch form pre-filled with existing values
  - Fixed `prefillForm()` for scheduled scans to parse and restore schedule fields (frequency, weekdays, day-of-month, start date/time, active status)
  - All scan types now support editing with no blank/default values on existing data

### [REQ-005] Add "Running" and "Active" status filters to non-scheduled scans
- **Type:** Enhancement
- **Priority:** Medium
- **Completed:** 2026-04-12
- **Summary:** Added Active, Error, and Canceled options to the status filter dropdown on the non-scheduled scans page.

### [REQ-006] Bulk edit scans by status group
- **Type:** Feature
- **Priority:** High
- **Completed:** 2026-04-12
- **Summary:** Added checkbox to each status group header. Checking it selects all scans in that group. Bulk action bar updates accordingly.

### [REQ-007] Change log page with export
- **Type:** Feature
- **Priority:** High
- **Completed:** 2026-04-12
- **Summary:**
  - New "History" tab in navbar showing all applied changes with timestamps
  - Filterable by search text and action type
  - CSV export via "Export CSV" button
  - Added `applied_at` column to `staged_changes` via migration
  - Persists across restarts (uses existing `staged_changes` table with `applied = 1`)

### [REQ-008] Bulk select by group for scheduled scans
- **Type:** Feature
- **Priority:** High
- **Completed:** 2026-04-12
- **Summary:**
  - Added group-header checkboxes to scheduled scans page (matching non-scheduled scans)
  - Checkbox selects/deselects all scans in that status group
  - Group checkbox syncs with individual row selections (supports indeterminate state)
  - Existing bulk actions (Activate, Deactivate, Change Profile, Delete) work with group selections

### [REQ-009] Fix edit form not prefilling when detail API fails
- **Type:** Bug
- **Priority:** High
- **Completed:** 2026-04-12
- **Summary:**
  - Fixed fallback logic in `scan_form.html` — the `/api/scheduled` (or `/api/scans`) list endpoint now runs as fallback whenever the detail API returns `{success: false}`, not only on network exceptions
  - Fixes the blank edit form in offline mode where the Qualys API detail call fails but doesn't throw
  - Both scheduled and non-scheduled edit paths fixed with the same pattern

### [REQ-010] Replace "Pending Changes" with "Launching Next 48h"
- **Type:** Enhancement
- **Priority:** Medium
- **Completed:** 2026-04-12
- **Summary:**
  - Replaced the "Pending Changes" metric card on the dashboard with "Launching Next 48h"
  - Shows the count of scheduled scan launches projected for the next 48 hours
  - Clicking the card switches the activity chart to the 48h forecast view
  - Backend uses existing `get_launch_forecast(48)` to compute the total

### [REQ-011] Line graph for all scan activity chart modes
- **Type:** Enhancement
- **Priority:** Low
- **Completed:** 2026-04-12
- **Summary:**
  - Changed the scan activity chart from bar graph (for forecast modes) to line graph for all time settings
  - All modes (Past 24h, Next 24/48/72h) now render as filled line charts with consistent styling
  - Past uses blue, forecast uses green — both with area fill

### [REQ-012] Show asset scan counts for completed scans
- **Type:** Feature
- **Priority:** High
- **Completed:** 2026-04-12
- **Summary:**
  - Extended `_parse_scans()` in `api_client.py` to extract `PROCESSED` and `TOTAL` host count fields from Qualys XML
  - Updated `get_scans()` and `get_recent_scans()` to include `processed` and `total_hosts` from raw data
  - Scan detail page now shows a "Scan Results" card with Hosts Scanned / Hosts Failed / Total Hosts for finished/error/canceled scans
  - Scan table rows show a compact host count indicator (e.g. "✓ 42 · ✗ 3 / 45") under the status badge

### [REQ-014] Tags page — scan details and Lookup integration
- **Type:** Enhancement
- **Priority:** Medium
- **Completed:** 2026-04-12
- **Summary:**
  - Tag table now shows scan details (title, status badge, target) instead of just raw refs
  - Each tag row has a "View in Lookup" button that opens the Lookup page pre-filtered by that tag
  - Scan titles link directly to their detail pages (scheduled or non-scheduled)
  - Updated `get_tag_report()` to join against scans/scheduled_scans tables for title, status, target data
  - Table upgraded to `data-table` class with 4 columns: Tag, Scan Count, Scans Using This Tag, Actions

### [REQ-015] Dashboard — Next scan status and past 24h results
- **Type:** Feature
- **Priority:** High
- **Completed:** 2026-04-12
- **Summary:**
  - Added two new cards between the scheduled metrics and the activity chart:
    - **Next Scheduled Scan**: Shows the soonest active scheduled scan with title, schedule, target, countdown timer, and launch date
    - **Past 24 Hours**: Shows succeeded (Finished) vs failed (Error/Canceled) scan counts from the last 24 hours
  - Both cards refresh when "Refresh All from Qualys" is clicked

### [REQ-016] Dashboard — Unified Scan Timeline, failed markers, drill-down
- **Type:** Enhancement
- **Priority:** High
- **Completed:** 2026-04-12
- **Summary:**
  - Replaced separate "Recent Scans" and "Upcoming Scheduled Scans" tables with a unified "📋 Scan Timeline" showing last 10 on-demand scans and next 10 upcoming scheduled scans, with directional arrows (◀/▶), type badges, and section headers
  - Added red failed scan markers on the activity chart: dashed red line with large red dots at hours where scans failed (Error/Canceled)
  - Past 24h drill-down panel (Succeeded/Failed click-through) moved inside the Scan Timeline card with smooth scroll-to behavior
  - "Launching Next 48h" card simplified to show count only
  - Chart legend auto-shows when failed overlay dataset is present
