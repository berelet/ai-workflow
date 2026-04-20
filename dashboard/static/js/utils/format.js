/**
 * Date/time formatting using current locale.
 */
function formatDate(date) {
    const locale = i18n.getLang() === 'uk' ? 'uk-UA' : 'en-US';
    return new Intl.DateTimeFormat(locale, {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
    }).format(new Date(date));
}

function formatRelativeTime(date) {
    const locale = i18n.getLang() === 'uk' ? 'uk-UA' : 'en-US';
    const diff = (Date.now() - new Date(date).getTime()) / 1000;
    const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
    if (diff < 60) return rtf.format(-Math.round(diff), 'second');
    if (diff < 3600) return rtf.format(-Math.round(diff / 60), 'minute');
    if (diff < 86400) return rtf.format(-Math.round(diff / 3600), 'hour');
    return rtf.format(-Math.round(diff / 86400), 'day');
}
