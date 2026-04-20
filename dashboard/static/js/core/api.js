/**
 * API fetch wrapper with HTTP-only cookie auth.
 * Cookies are sent automatically via credentials: 'same-origin'.
 * On 401, redirects to login page (unless on login page already).
 * Throws ApiError on non-2xx responses.
 */
class ApiError extends Error {
    constructor(status, detail) {
        super(detail || `HTTP ${status}`);
        this.status = status;
        this.detail = detail;
    }
}

const API = {
    _base: '',
    /** Set to true on login.html to prevent 401 redirect loop */
    skipAuthRedirect: false,

    async _fetch(url, options = {}) {
        const headers = { ...(options.headers || {}) };
        if (!(options.body instanceof FormData) && !headers['Content-Type']) {
            headers['Content-Type'] = 'application/json';
        }
        const response = await fetch(this._base + url, {
            ...options,
            headers,
            credentials: 'same-origin',
        });
        if (response.status === 401 && !this.skipAuthRedirect) {
            window.location.href = '/login.html';
            throw new ApiError(401, 'Unauthorized');
        }
        if (!response.ok) {
            let detail = `HTTP ${response.status}`;
            try {
                const body = await response.json();
                detail = body.detail || JSON.stringify(body);
            } catch (e) { /* non-JSON error body */ }
            throw new ApiError(response.status, detail);
        }
        return response;
    },

    async get(url) {
        const r = await this._fetch(url);
        return r.json();
    },

    async post(url, body) {
        const r = await this._fetch(url, {
            method: 'POST',
            body: JSON.stringify(body),
        });
        return r.json();
    },

    async postForm(url, formData) {
        const r = await this._fetch(url, {
            method: 'POST',
            body: formData,
            headers: {},
        });
        return r.json();
    },

    async put(url, body) {
        const r = await this._fetch(url, {
            method: 'PUT',
            body: JSON.stringify(body),
        });
        return r.json();
    },

    async del(url) {
        const r = await this._fetch(url, { method: 'DELETE' });
        return r.json();
    },

    async raw(url, options = {}) {
        return this._fetch(url, options);
    },
};
