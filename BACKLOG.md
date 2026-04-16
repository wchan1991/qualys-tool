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
### [REQ-013] Expansion - Import Function
- **Type:** Feature
- **Priority:** Medium
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

### [REQ-023] Scan View - Search enhancements
- **Type:** Enhancement
- **Priority:** High
- **Completed:** 2026-04-15
- **Description:** Wildcard/fuzzy search with autocomplete suggestions, expanded
  to search option profile names and IDs.
- **Changes:**
  - `templates/scans.html`: search now uses regex with `*` wildcard support,
    searches `title`, `ref`, `target`, and `option_profile`. Autocomplete
    dropdown shows matching titles/profiles as you type (min 2 chars).
  - `templates/scheduled.html`: same search upgrade — searches `title`,
    `target`, `owner`, and `option_profile` with wildcard + autocomplete.
  - `static/style.css`: added `.search-suggestions` and `.search-suggestion-item`
    styles (dark/light mode aware).

### [REQ-022] Update Option Profile Menu
- **Type:** Enhancement
- **Priority:** High
- **Completed:** 2026-04-15
- **Description:** Removed Beta column from profiles table, moved test/verify
  into a sidebar, added bulk select + delete.
- **Changes:**
  - `templates/option_profiles.html`: Redesigned with two-panel layout —
    main table (left) with checkboxes, per-row delete button, and bulk delete
    bar; sidebar (right) with test resolution and info card. Removed redundant
    Beta column (beta badge still shows inline in Title).
  - `src/api_client.py`: added `delete_option_profile(profile_id)` method.
  - `app.py`: added `POST /api/option-profiles/delete` endpoint accepting
    `{ids: [...]}` with per-profile error handling + cache bust.

### [REQ-021] Enhancing Staging Calls
- **Type:** Enhancement
- **Priority:** High
- **Completed:** 2026-04-15
- **Description:** All staging operations now run in the background — modals
  close immediately on submit, POST fires async, toast notification appears
  on completion, staging badge updates automatically.
- **Changes:**
  - `static/app.js`: added `stageInBackground(url, body, label)` helper —
    fire-and-forget fetch with toast + badge update on resolve.
  - Converted all 8 staging calls across 6 templates:
    `scans.html` (2), `scheduled.html` (3), `scan_detail.html` (1),
    `scheduled_detail.html` (1), `scan_form.html` (1).
  - All `async function confirmStage/confirmAction/bulkAction` → synchronous
    functions that close UI and call `stageInBackground()`.

### [REQ-020] Performance, staging dedup, nav restructure, dark mode, git hygiene
- **Type:** Bug + Enhancement
- **Priority:** High
- **Completed:** 2026-04-15
- **Description:** Batch of 7 improvements to reduce API calls, fix duplicate
  staging entries, protect production DB from git overwrites, fix dark mode
  colors, and consolidate nav tabs.
- **Changes:**
  - **P0 — Staging dedup**: `src/database.py` `stage_change()` now checks for
    existing pending row `(scan_ref, change_type, applied=0)` before INSERT.
    Returns existing ID if found. `templates/scheduled.html` disables bulk
    buttons during fetch to prevent double-click.
  - **P1a — Dashboard double-fetch**: Merged `loadNext48h()` into
    `loadDashboard()` in `templates/index.html` — one `/api/dashboard` call
    instead of two per page load.
  - **P1b — Forecast reuse**: `src/scan_manager.py` `get_launch_forecast()`
    accepts optional `scheduled=` param. `get_dashboard()` passes its
    already-fetched list, eliminating a redundant DB read.
  - **P1c — Health cache**: `app.py` health endpoint now uses
    `get_target_sources()` (5-min TTL cache) instead of a live
    `list_option_profiles()` call every 60 seconds.
  - **P1d — Scanners cache**: `get_scanners()` routes through
    `get_target_sources()` cache instead of hitting the Qualys API directly.
  - **P2 — .gitignore**: Added `data/qualys_scans.db`, `__pycache__/`, `*.pyc`.
    Untracked DB from git. Added `data/.gitkeep`. Git pull no longer overwrites
    production scan database.
  - **P3 — Dark mode**: Replaced hardcoded inline colors in `scheduled.html`,
    `staging.html` with CSS variables (`--bg-tertiary`, `--text-secondary`,
    `--danger`).
  - **P4 — Nav restructure**: Consolidated 10 flat nav tabs into grouped
    dropdowns: `[Scans ▾]` (Non-Scheduled, Scheduled, Calendar) and
    `[Scan Settings ▾]` (Tags, Scanners, Profiles). `templates/base.html` +
    `static/style.css`.
  - **P5 — Seed data**: Added 3 MODIFY staged entries to `seed_test_data.py`
    with profile-change payloads (2 with resolved ID, 1 title-only for
    warning-path testing).

### [REQ-019] Option Profiles tab + fix bulk change picking wrong profile
- **Type:** Bug + Feature
- **Priority:** High
- **Completed:** 2026-04-15
- **Description:** Bulk "Change Profile" action silently applied the wrong
  profile when two profiles shared a name prefix (e.g. `Foo` vs `Foo (beta)`).
  Root cause: the staging payload used `option_profile` (title only), but
  `_build_scan_form()` only read `option_id` / `option_title` — so no profile
  parameter was sent to Qualys, leaving the original profile in place.
- **Changes:**
  - `src/api_client.py`: `_build_scan_form()` now falls back to `option_profile`
    as a title alias; added `resolve_option_profile()` helper that exact-matches
    by ID or title and raises `QualysError` with similar-profile hints when
    ambiguous/missing.
  - `app.py`: `/api/stage/bulk` now resolves the profile to an ID server-side
    before staging, so the applied payload always carries `option_id`.
  - New `/option-profiles` page (nav: ⚙️ Profiles) listing all VM profiles live
    from Qualys with ID, title, default/beta badges, search, and a per-row
    "🧪 Test" button.
  - New API endpoints: `/api/option-profiles` (uncached), `/api/option-profiles/resolve?q=…`.
  - `templates/scheduled.html`: bulk modal dropdown now keys by profile ID,
    shows `title — id=N` in each option, previews the resolved ID+title,
    and has a "🧪 Verify against Qualys" button that hits the resolve endpoint.
  - `templates/staging.html`: change rows now show the resolved profile ID
    next to the title, and warn with ⚠ if only a title is staged (legacy rows).
- **Test process:**
  1. Open ⚙️ Profiles — confirm both beta and non-beta profiles are listed
     with distinct IDs.
  2. On Scheduled, select a scan and open Change Profile — each option shows
     `Title — id=N`, and picking one reveals the preview box.
  3. Click "🧪 Verify against Qualys" — should confirm the exact title/ID.
  4. Stage the change — staging page shows the resolved ID, not just the title.
  5. Apply — Qualys receives `option_id=N`, which can't collide with a
     similarly-named profile.

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
