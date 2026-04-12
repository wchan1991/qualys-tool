/* ============================================================
   Qualys Scan Manager - JavaScript
   ============================================================ */

// ============================================================
// THEME
// ============================================================

function initTheme() {
    const saved = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = saved || (prefersDark ? 'dark' : 'light');
    
    document.documentElement.setAttribute('data-theme', theme);
    updateThemeButton(theme);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateThemeButton(next);
}

function updateThemeButton(theme) {
    const btn = document.getElementById('theme-toggle');
    if (btn) {
        btn.textContent = theme === 'dark' ? '☀️' : '🌙';
    }
}

// ============================================================
// CONNECTION STATUS
// ============================================================

async function checkConnection() {
    const dot = document.getElementById('connection-status');
    if (!dot) return;

    try {
        const res = await fetch('/api/health');
        const json = await res.json();

        if (json.success && json.data.status === 'connected') {
            dot.classList.add('connected');
            dot.classList.remove('error');
            dot.title = `Connected to ${json.data.api_url}`;
        } else {
            dot.classList.add('error');
            dot.classList.remove('connected');
            dot.title = json.data.message || 'Not connected';
        }

        // Offline mode UI
        const offline = json.success && json.data.offline;
        const banner = document.getElementById('offline-banner');
        if (banner) banner.classList.toggle('hidden', !offline);
        // Disable "Make It So" button when offline
        const applyBtn = document.getElementById('apply-btn');
        if (applyBtn) {
            applyBtn.disabled = !!offline;
            applyBtn.title = offline ? 'Applying changes is disabled in offline mode' : '';
        }
    } catch (e) {
        dot.classList.add('error');
        dot.classList.remove('connected');
        dot.title = 'Connection error';
    }
}

// ============================================================
// STAGING BADGE
// ============================================================

async function updateStagingBadge() {
    const badge = document.getElementById('staging-badge');
    if (!badge) return;
    
    try {
        const res = await fetch('/api/staged');
        const json = await res.json();
        
        if (json.success && json.data.length > 0) {
            badge.textContent = json.data.length;
            badge.classList.remove('hidden');
        } else {
            badge.classList.add('hidden');
        }
    } catch (e) {
        badge.classList.add('hidden');
    }
}

// ============================================================
// TOAST NOTIFICATIONS
// ============================================================

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    if (!toast) return;
    
    toast.textContent = message;
    toast.className = `toast ${type}`;
    
    // Auto hide after 4 seconds
    setTimeout(() => {
        toast.classList.add('hidden');
    }, 4000);
}

// ============================================================
// UTILITIES
// ============================================================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    try {
        let s = String(dateStr).trim();
        // Qualys XML dates look like "2024/01/15 14:30:00" (UTC) — normalise
        if (/^\d{4}\/\d{2}\/\d{2}/.test(s)) {
            s = s.replace(/\//g, '-');
            // Append Z so the browser treats it as UTC and converts to local
            if (!/[Zz]|[+-]\d{2}:?\d{2}$/.test(s)) s += 'Z';
        }
        const date = new Date(s);
        if (isNaN(date.getTime())) return dateStr;
        return date.toLocaleString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch (e) {
        return dateStr;
    }
}

// ============================================================
// INITIALIZATION
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    checkConnection();
    updateStagingBadge();

    // Theme toggle
    const themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) {
        themeBtn.addEventListener('click', toggleTheme);
    }

    // Refresh connection status periodically
    setInterval(checkConnection, 60000);
    setInterval(updateStagingBadge, 30000);
});

// ============================================================
// DROPDOWN / OVERFLOW MENU (F18)
// ============================================================

function toggleDropdown(id) {
    const el = document.getElementById(id);
    if (!el) return;
    const wasHidden = el.classList.contains('hidden');

    // Close any other open dropdowns first
    document.querySelectorAll('.dropdown-menu').forEach(menu => {
        if (menu !== el) menu.classList.add('hidden');
    });

    el.classList.toggle('hidden');

    if (wasHidden) {
        // Attach a one-shot outside-click closer
        const closer = (ev) => {
            if (!el.contains(ev.target) && !ev.target.closest(`[data-dropdown="${id}"]`)) {
                el.classList.add('hidden');
                document.removeEventListener('click', closer);
            }
        };
        setTimeout(() => document.addEventListener('click', closer), 0);
    }
}
