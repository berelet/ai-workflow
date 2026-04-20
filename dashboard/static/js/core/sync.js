/**
 * Multi-user sync: polls for changes and shows "updates available" banner.
 * Similar to Jira's change notification.
 */
const Sync = {
    _interval: null,
    _lastUpdatedAt: null,
    _pollMs: 15000,

    start() {
        this.stop();
        this._interval = setInterval(() => this.check(), this._pollMs);
    },

    stop() {
        if (this._interval) {
            clearInterval(this._interval);
            this._interval = null;
        }
    },

    async check() {
        if (!AppState.currentProject) return;
        try {
            const data = await API.get(`/api/projects/${AppState.currentProject}/updated-at`);
            if (this._lastUpdatedAt && data.updated_at !== this._lastUpdatedAt) {
                this.showBanner();
            }
            this._lastUpdatedAt = data.updated_at;
        } catch (e) { /* silent */ }
    },

    showBanner() {
        const banner = document.getElementById('sync-banner');
        if (banner) {
            banner.classList.remove('hidden');
            banner.textContent = i18n.t('sync.updates_available');
        }
    },

    dismiss() {
        const banner = document.getElementById('sync-banner');
        if (banner) banner.classList.add('hidden');
        this._lastUpdatedAt = null;
    },

    reset() {
        this._lastUpdatedAt = null;
        this.dismiss();
    },
};
