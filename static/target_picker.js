/**
 * Target Picker — reusable vanilla JS module for scan forms.
 * Renders a type selector + dynamic value input, and provides getValue().
 */

class TargetPicker {
    /**
     * @param {HTMLElement} container - element to render into
     * @param {Object} sources - {asset_groups, tags} from /api/target-sources
     * @param {Object} initial - {type, value} to pre-populate
     */
    constructor(container, sources, initial = {}) {
        this.container = container;
        this.sources = sources || {};
        this.initial = initial;
        this._render();
    }

    _render() {
        this.container.innerHTML = `
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:flex-start">
                <select id="tp-type" class="input" style="min-width:140px" onchange="window._tp_onTypeChange(this)">
                    <option value="ip">IP / Range</option>
                    <option value="asset_group">Asset Group</option>
                    <option value="tag">Tag</option>
                </select>
                <div id="tp-value-wrap" style="flex:1;min-width:200px"></div>
            </div>
            <div class="text-muted" style="font-size:0.8rem;margin-top:0.3rem">
                For IPs/ranges use comma-separated values, e.g. <code>10.0.0.1, 10.0.0.0/24</code>
            </div>
        `;

        // Expose change handler globally (simple approach for inline onchange)
        window._tp_onTypeChange = (sel) => this._onTypeChange(sel.value);

        const typeEl = this.container.querySelector('#tp-type');
        if (this.initial.type) {
            typeEl.value = this.initial.type;
        }
        this._onTypeChange(typeEl.value);
    }

    _onTypeChange(type) {
        const wrap = this.container.querySelector('#tp-value-wrap');
        const initVal = this.initial.value || '';

        if (type === 'asset_group') {
            const groups = this.sources.asset_groups || [];
            if (groups.length) {
                wrap.innerHTML = `<select id="tp-value" class="input" style="width:100%">
                    ${groups.map(g => `<option value="${this._esc(g.title || g.name || g.id)}" ${(g.title || g.name) === initVal ? 'selected' : ''}>${this._esc(g.title || g.name || g.id)}</option>`).join('')}
                </select>`;
            } else {
                wrap.innerHTML = `<input id="tp-value" type="text" class="input" style="width:100%"
                    placeholder="Asset group name" value="${this._esc(initVal)}">`;
            }
        } else if (type === 'tag') {
            const tags = this.sources.tags || [];
            if (tags.length) {
                wrap.innerHTML = `<select id="tp-value" class="input" style="width:100%">
                    ${tags.map(t => `<option value="${this._esc(t.name || t.id)}" ${(t.name) === initVal ? 'selected' : ''}>${this._esc(t.name || t.id)}</option>`).join('')}
                </select>`;
            } else {
                wrap.innerHTML = `<input id="tp-value" type="text" class="input" style="width:100%"
                    placeholder="Tag name" value="${this._esc(initVal)}">`;
            }
        } else {
            // ip / range — free text
            wrap.innerHTML = `<input id="tp-value" type="text" class="input" style="width:100%"
                placeholder="e.g. 10.0.0.1, 192.168.0.0/24" value="${this._esc(initVal)}">`;
        }
    }

    /** Returns {type, value} or null if empty. */
    getValue() {
        const typeEl = this.container.querySelector('#tp-type');
        const valueEl = this.container.querySelector('#tp-value');
        if (!typeEl || !valueEl) return null;
        const type = typeEl.value;
        const value = valueEl.value.trim();
        if (!value) return null;
        return { type, value };
    }

    _esc(text) {
        if (text == null) return '';
        return String(text).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
}
