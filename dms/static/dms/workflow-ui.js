(() => {
  'use strict';
  const prefixes = document.getElementById('document-number-prefixes');
  const kind = document.getElementById('id_document_type');
  const number = document.getElementById('id_number');
  if (prefixes && kind && number) {
    const values = JSON.parse(prefixes.textContent);
    const update = () => { number.value = values[kind.value] ? `${values[kind.value]}-…` : ''; };
    kind.addEventListener('change', update);
    update();
  }
  const bell = document.querySelector('[data-task-summary]');
  if (!bell) return;
  let busy = false;
  const refresh = async () => {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const response = await fetch(bell.dataset.taskSummary, {credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json'}});
      if (!response.ok || response.redirected || !response.headers.get('content-type')?.includes('application/json')) return;
      const counts = await response.json();
      if (!Number.isSafeInteger(counts.work_count) || counts.work_count < 0) return;
      bell.querySelector('[data-task-count]').textContent = String(counts.work_count);
      bell.dataset.pendingApprovals = String(counts.pending_count);
      bell.classList.toggle('has-tasks', counts.work_count > 0);
      const label = `Aufgaben, ${counts.work_count} offen, davon ${counts.pending_count} Freigabeanfragen`;
      bell.setAttribute('aria-label', label);
      bell.title = label;
    } catch { /* Keep the last known count during temporary network failures. */ }
    finally { busy = false; }
  };
  window.addEventListener('focus', refresh);
  document.addEventListener('visibilitychange', refresh);
  setInterval(refresh, 15000);
  refresh();
})();
