/**
 * WebSocket manager.
 * Cookies are sent automatically on handshake (same-origin).
 */
const WS = {
    /**
     * Create a WebSocket connection.
     * @param {string} path - e.g., '/ws/terminal'
     * @param {Object} options - {onmessage, onclose, onerror, onopen}
     * @returns {WebSocket}
     */
    connect(path, options = {}) {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${proto}//${location.host}${path}`;
        const ws = new WebSocket(url);

        if (options.onopen) ws.onopen = options.onopen;
        if (options.onmessage) ws.onmessage = options.onmessage;
        if (options.onclose) ws.onclose = options.onclose;
        if (options.onerror) ws.onerror = options.onerror;

        return ws;
    },
};
