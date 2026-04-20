/**
 * Internationalization module.
 * Loads translations from /static/lang/{lang}.json.
 * Applies to DOM via data-i18n attributes.
 *
 * Usage:
 *   <button data-i18n="topbar.backlog">Бэклог</button>
 *   <input data-i18n-placeholder="terminal.prompt_placeholder">
 *   i18n.t('common.save')  // returns translated string
 *   i18n.t('task.count', {n: 5})  // with interpolation
 */
const i18n = {
    _lang: 'uk',
    _strings: {},
    _loaded: false,

    async load(lang) {
        if (!lang) lang = 'uk';
        try {
            const r = await fetch(`/static/lang/${lang}.json`);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            this._strings = await r.json();
            this._lang = lang;
            this._loaded = true;
            localStorage.setItem('ai_workflow_lang', lang);
        } catch (e) {
            console.warn(`i18n: failed to load ${lang}, falling back to uk`, e);
            if (lang !== 'uk') {
                await this.load('uk');
            }
        }
    },

    getLang() {
        return this._lang;
    },

    /**
     * Get translated string by dot-separated key.
     * Supports {param} interpolation.
     */
    t(key, params) {
        let s = this._strings[key] || key;
        if (params) {
            for (const [k, v] of Object.entries(params)) {
                s = s.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
            }
        }
        return s;
    },

    /**
     * Apply translations to all DOM elements with data-i18n* attributes.
     */
    apply() {
        // Text content
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            if (key && this._strings[key]) {
                el.textContent = this._strings[key];
            }
        });
        // Placeholders
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.getAttribute('data-i18n-placeholder');
            if (key && this._strings[key]) {
                el.placeholder = this._strings[key];
            }
        });
        // Titles
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            if (key && this._strings[key]) {
                el.title = this._strings[key];
            }
        });
    },

    /**
     * Switch language, reload translations, re-apply to DOM.
     */
    async setLang(lang) {
        await this.load(lang);
        this.apply();
        // Save preference to server if authenticated
        try {
            await API.put('/api/auth/me', { lang });
        } catch (e) { /* not logged in or network error */ }
    },

    /**
     * Get speech recognition language code for Web Speech API.
     */
    getSpeechLang() {
        return this._lang === 'uk' ? 'uk-UA' : 'en-US';
    },
};
