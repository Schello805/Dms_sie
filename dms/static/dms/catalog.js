/* Live catalogue, debounced search and cancellable lazy pagination. */
(() => {
  const form = document.getElementById('document-filters');
  const rows = document.getElementById('document-rows');
  const navigation = document.getElementById('document-pagination');
  const status = document.getElementById('table-load-status');
  if (!form || !rows || !navigation || !status || !window.fetch || !window.AbortController) return;
  const search = form.querySelector('[name=q]');
  const area = rows.closest('.table-wrap');
  const count = document.getElementById('document-count');
  let currentUrl = new URL(location.href);
  let nextUrl = navigation.querySelector('[data-load-next]')?.href || null;
  let controller = null;
  let generation = 0;
  let timer;
  let paused = false;
  let restoring = Boolean(window.imsCatalogRestore?.rows > rows.children.length);
  const restore = window.imsCatalogRestore;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'secondary';
  button.textContent = 'Weitere Dokumente laden';
  navigation.replaceChildren(button);
  const observer = window.IntersectionObserver ? new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) load(nextUrl, true);
  }, {root: area, rootMargin: '250px'}) : null;

  function watch() {
    observer?.disconnect();
    button.hidden = !nextUrl;
    button.disabled = Boolean(controller) || paused;
    if (nextUrl && !controller && !paused && rows.lastElementChild) observer?.observe(rows.lastElementChild);
  }
  function invalidate() {
    clearTimeout(timer);
    generation++;
    controller?.abort();
    controller = null;
    rows.removeAttribute('aria-busy');
    observer?.disconnect();
  }
  function filterUrl() {
    const url = new URL(form.action || location.href);
    url.search = new URLSearchParams(new FormData(form)).toString();
    url.searchParams.set('q', search.value.trim());
    url.searchParams.delete('page');
    url.searchParams.delete('fragment');
    return url;
  }
  function updateSorting() {
    document.querySelectorAll('.table-sort').forEach(link => {
      const key = new URL(link.href).searchParams.get('sort');
      const selected = currentUrl.searchParams.get('sort') === key;
      const descending = currentUrl.searchParams.get('direction') === 'desc';
      const url = new URL(currentUrl);
      url.searchParams.delete('page');
      url.searchParams.set('sort', key);
      url.searchParams.set('direction', selected && !descending ? 'desc' : 'asc');
      link.href = url;
      link.closest('th').setAttribute('aria-sort', selected ? (descending ? 'descending' : 'ascending') : 'none');
      link.querySelector('span').textContent = selected ? (descending ? '↓' : '↑') : '↕';
    });
  }
  async function load(target, append = false) {
    if (!target || paused || (append && controller)) return;
    if (!append) { invalidate(); restoring = false; }
    const turn = generation;
    const active = new AbortController();
    controller = active;
    watch();
    rows.setAttribute('aria-busy', 'true');
    status.textContent = append ? 'Weitere Dokumente werden geladen …' : 'Dokumente werden gesucht …';
    try {
      const url = new URL(target, location.href);
      url.searchParams.set('fragment', '1');
      const response = await fetch(url, {signal: active.signal, credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}});
      if (!response.ok || response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Invalid response');
      const data = await response.json();
      if (turn !== generation) return;
      if (typeof data.html !== 'string' || !Number.isInteger(data.total_count)) throw new Error('Invalid fragment');
      const parsed = new DOMParser().parseFromString('<table><tbody>' + data.html + '</tbody></table>', 'text/html');
      const fresh = [...parsed.querySelector('tbody').children];
      if (append) rows.append(...fresh);
      else {
        rows.replaceChildren(...fresh);
        area.scrollTop = 0;
        currentUrl = new URL(target, location.href);
        currentUrl.searchParams.delete('fragment');
        history.replaceState(null, '', currentUrl);
        updateSorting();
      }
      nextUrl = data.next_url;
      count.textContent = data.total_count;
      status.textContent = `${data.total_count} Treffer.${nextUrl ? ' Weitere Dokumente werden beim Scrollen geladen.' : ''}`;
      if (restoring && (rows.children.length >= restore.rows || !nextUrl)) {
        restoring = false;
        area.scrollTop = restore.scroll;
        window.scrollTo(0, restore.pageScroll);
      }
    } catch (error) {
      if (turn !== generation || error.name === 'AbortError') return;
      paused = true;
      restoring = false;
      status.textContent = 'Laden fehlgeschlagen. Bitte über „Filtern“ oder „Weitere Dokumente laden“ erneut versuchen.';
    } finally {
      if (turn === generation) {
        controller = null;
        rows.removeAttribute('aria-busy');
        // A failed request can be retried manually, without an automatic retry loop.
        if (paused) { observer?.disconnect(); button.disabled = false; }
        else watch();
        if (restoring && nextUrl && !paused) load(nextUrl, true);
      }
    }
  }
  function schedule(event) {
    invalidate();
    restoring = false;
    paused = true;
    watch();
    if (event?.isComposing) return;
    const term = search.value.trim();
    if (term.length > 0 && [...term].length < 3) {
      status.textContent = 'Für die Direktsuche mindestens 3 Zeichen eingeben.';
      return;
    }
    timer = setTimeout(() => { paused = false; load(filterUrl()); }, 300);
  }
  search.addEventListener('input', schedule);
  search.addEventListener('compositionend', schedule);
  form.addEventListener('change', event => {
    if (event.target === search) return;
    invalidate(); paused = false; load(filterUrl());
  });
  form.addEventListener('submit', event => {
    event.preventDefault(); invalidate(); paused = false; load(filterUrl());
  });
  document.querySelectorAll('.table-sort').forEach(link => link.addEventListener('click', event => {
    if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); invalidate(); paused = false;
    const url = new URL(link.href);
    for (const name of ['sort', 'direction']) {
      let field = form.querySelector(`[name=${name}]`);
      if (!field) { field = document.createElement('input'); field.type = 'hidden'; field.name = name; form.append(field); }
      field.value = url.searchParams.get(name);
    }
    load(url);
  }));
  button.addEventListener('click', () => { paused = false; load(nextUrl, true); });
  watch();
  if (restoring) load(nextUrl, true);
})();
