/* Progressive enhancement: ordinary pagination remains usable without JS. */
(() => {
  const navigation = document.getElementById('document-pagination');
  const rows = document.getElementById('document-rows');
  const status = document.getElementById('table-load-status');
  if (!navigation || !rows || !status) return;

  const nextLink = navigation.querySelector('[data-load-next]');
  if (!nextLink || !window.fetch || !window.IntersectionObserver) return;

  let nextUrl = nextLink.href;
  let busy = false;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'secondary';
  button.textContent = 'Weitere Dokumente laden';
  navigation.replaceChildren(button);

  async function loadNextPage() {
    if (busy || !nextUrl) return;
    busy = true;
    button.disabled = true;
    button.textContent = 'Wird geladen …';
    rows.setAttribute('aria-busy', 'true');
    status.textContent = 'Weitere Dokumente werden geladen …';

    try {
      const url = new URL(nextUrl, location.href);
      url.searchParams.set('fragment', '1');
      const response = await fetch(url, {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok || response.redirected ||
          !response.headers.get('content-type')?.includes('application/json')) {
        throw new Error('Invalid page response');
      }
      const data = await response.json();
      if (typeof data.html !== 'string') throw new Error('Invalid row fragment');

      // HTML comes from the same protected, autoescaped server template.
      const parsed = new DOMParser().parseFromString(
        '<table><tbody>' + data.html + '</tbody></table>', 'text/html');
      rows.append(...parsed.querySelector('tbody').children);
      nextUrl = data.next_url;
      status.textContent = nextUrl ? 'Weitere Dokumente geladen.' : 'Alle Dokumente geladen.';
      if (!nextUrl) {
        observer.disconnect();
        navigation.remove();
      }
    } catch (error) {
      observer.disconnect();
      status.textContent = 'Nachladen nicht möglich. Bitte erneut versuchen oder die Seite neu laden.';
    } finally {
      busy = false;
      button.disabled = false;
      button.textContent = 'Weitere Dokumente laden';
      rows.removeAttribute('aria-busy');
    }
  }

  const observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) loadNextPage();
  }, { rootMargin: '250px' });
  button.addEventListener('click', loadNextPage);
  observer.observe(navigation);
})();
