/* Per-tab navigation state only. Never store document content or form values. */
(() => {
  const key = 'ims:catalog:' + (document.body.dataset.account || 'guest');
  const rows = document.getElementById('document-rows');
  let saved;
  try { saved = JSON.parse(sessionStorage.getItem(key) || 'null'); } catch (_) { return; }
  if (rows) {
    const save = () => {
      try {
        sessionStorage.setItem(key, JSON.stringify({
          url: location.pathname + location.search,
          scroll: document.querySelector('.table-wrap')?.scrollTop || 0,
          pageScroll: window.scrollY,
          rows: rows.children.length,
        }));
      } catch (_) { /* Browsing still works with storage disabled. */ }
    };
    document.addEventListener('click', event => {
      if (event.target.closest('[data-table-reset]')) {
        try { sessionStorage.removeItem(key); } catch (_) {}
        return;
      }
      if (event.target.closest('#document-rows a')) save();
    });
    if (saved && saved.url === location.pathname + location.search) {
      window.imsCatalogRestore = saved;
      requestAnimationFrame(() => {
        if (rows.children.length >= saved.rows) {
          document.querySelector('.table-wrap').scrollTop = saved.scroll;
          window.scrollTo(0, saved.pageScroll);
        }
      });
    }
  } else if (saved && typeof saved.url === 'string' &&
             (/^\/(documents\/)?\?/.test(saved.url) || ['/','/documents/'].includes(saved.url))) {
    document.querySelectorAll('[data-catalog-back]').forEach(link => {
      link.href = saved.url;
    });
  }
  document.querySelectorAll('form[action="/logout/"]').forEach(form => {
    form.addEventListener('submit', () => {
      try {
        for (const item of Object.keys(sessionStorage)) {
          if (item.startsWith('ims:catalog:')) sessionStorage.removeItem(item);
        }
      } catch (_) {}
    });
  });
})();
