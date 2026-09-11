/* Shared presentation behavior; authentication remains on the server. */
(() => {
    const node = document.getElementById('portal-brand-data');
    window.portalBrand = node ? JSON.parse(node.textContent) : {};
    document.querySelectorAll('.rec-tab').forEach(tab => {
        if (tab.tagName === 'BUTTON') return;
        tab.setAttribute('role', 'button');
        tab.tabIndex = 0;
        tab.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                tab.click();
            }
        });
    });
})();
