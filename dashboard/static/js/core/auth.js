/**
 * Auth module — works with HTTP-only cookies (no localStorage token).
 * User info is fetched from /api/auth/me.
 */
const Auth = {
    _user: null,

    async fetchUser() {
        try {
            const data = await API.get('/api/auth/me');
            this._user = data.user;
            return this._user;
        } catch (e) {
            this._user = null;
            return null;
        }
    },

    getUser() {
        return this._user;
    },

    isAuthenticated() {
        return this._user !== null;
    },

    isSuperadmin() {
        return this._user?.is_superadmin === true;
    },

    getUserLang() {
        return this._user?.lang || localStorage.getItem('ai_workflow_lang') || 'uk';
    },

    async login(email, password) {
        const data = await API.post('/api/auth/login', { email, password });
        this._user = data.user;
        return data;
    },

    async register(email, password, displayName) {
        const data = await API.post('/api/auth/register', {
            email,
            password,
            display_name: displayName,
        });
        this._user = data.user;
        return data;
    },

    async logout() {
        try {
            await API.post('/api/auth/logout');
        } catch (e) { /* ignore */ }
        this._user = null;
        window.location.href = '/login.html';
    },

    async updateProfile(data) {
        return API.put('/api/auth/me', data);
    },

    /**
     * Check if user is authenticated. If not, redirect to login.
     * Call at the top of protected pages.
     */
    async requireAuth() {
        const user = await this.fetchUser();
        if (!user) {
            window.location.href = '/login.html';
            return null;
        }
        return user;
    },

    /**
     * Check if user is superadmin. If not, redirect to dashboard.
     */
    async requireSuperadmin() {
        const user = await this.requireAuth();
        if (user && !user.is_superadmin) {
            window.location.href = '/';
            return null;
        }
        return user;
    },
};
