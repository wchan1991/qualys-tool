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

## Approved

<!-- Items approved for implementation -->

## In Progress

<!-- Items currently being worked on -->

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
