(() => {
  const form = document.getElementById('launch-session-form');
  const status = document.getElementById('launch-status');
  if (!form) return;

  const minimumSplashMs = 2000;
  const startedAt = performance.now();

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/service-worker.js', { scope: '/' }).catch(() => {});
  }

  function csrfToken() {
    return form.querySelector('[name="csrfmiddlewaretoken"]')?.value || '';
  }

  async function startFreshLogin() {
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrfToken() },
        body: new FormData(form),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok !== true) throw new Error('session_clear_failed');

      const remaining = Math.max(0, minimumSplashMs - (performance.now() - startedAt));
      window.setTimeout(() => window.location.replace('/admin-panel/login/?pwa_ready=1'), remaining);
    } catch (error) {
      if (status) status.textContent = 'Esperando conexión segura…';
      window.setTimeout(startFreshLogin, 1500);
    }
  }

  startFreshLogin();
})();