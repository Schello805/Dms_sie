/* Shared interactions. No document data is stored in the browser. */
(() => {
  const AUTO_DISMISS_MS = 8000;
  const transientLevels = new Set(['success', 'info', 'debug']);

  function initializeToast(toast) {
    const close = toast.querySelector('.toast-close');
    close.hidden = false;
    let timer;

    function pause() {
      clearTimeout(timer);
    }

    function resume() {
      pause();
      if (transientLevels.has(toast.dataset.level)) {
        timer = setTimeout(() => toast.remove(), AUTO_DISMISS_MS);
      }
    }

    close.addEventListener('click', () => {
      pause();
      toast.remove();
    });
    toast.addEventListener('mouseenter', pause);
    toast.addEventListener('mouseleave', resume);
    toast.addEventListener('focusin', pause);
    toast.addEventListener('focusout', () => {
      if (!toast.contains(document.activeElement)) resume();
    });
    resume();
  }

  function initializeAccountMenu(menu) {
    document.addEventListener('click', event => {
      if (!menu.contains(event.target)) menu.open = false;
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && menu.open) {
        menu.open = false;
        menu.querySelector('summary').focus();
      }
    });
  }

  // Keep submit-button values intact: disabling them would drop action/intent.
  document.querySelectorAll('form[method="post"]').forEach(form => {
    const comment = form.querySelector('[name="comment"]');
    form.addEventListener('submit', event => {
      if (comment && event.submitter?.hasAttribute('data-require-comment') && !comment.value.trim()) {
        event.preventDefault();
        comment.setCustomValidity('Bitte begründe die Ablehnung für den Autor.');
        comment.reportValidity();
        comment.focus();
        return;
      }
      if (form.dataset.submitting) {
        event.preventDefault();
        return;
      }
      form.dataset.submitting = 'true';
      form.setAttribute('aria-busy', 'true');
    });
    if (comment) {
      comment.addEventListener('input', () => comment.setCustomValidity(''));
      form.querySelectorAll('button[type="submit"], button[name="action"]').forEach(button => {
        button.addEventListener('click', () => comment.setCustomValidity(''));
      });
    }
  });
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('form[data-submitting]').forEach(form => {
      delete form.dataset.submitting;
      form.removeAttribute('aria-busy');
    });
  });

  let dirty = false;
  document.querySelectorAll('form[method="post"]').forEach(form => {
    form.addEventListener('input', event => { if (event.target.type !== 'hidden') dirty = true; });
    form.addEventListener('submit', event => {
      if (!event.defaultPrevented) dirty = false;
    });
  });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
  window.addEventListener('pageshow', () => { dirty = false; });

  document.querySelectorAll('[data-toast]').forEach(initializeToast);
  const menu = document.querySelector('.account-menu');
  if (menu) initializeAccountMenu(menu);
})();
