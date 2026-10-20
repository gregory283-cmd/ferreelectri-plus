(() => {
  const status = document.getElementById('launch-status');
  if (!status) return;

  const minimumSplashMs = 2000;
  const startedAt = performance.now();

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/service-worker.js', { scope: '/' }).catch(() => {});
  }

  const remaining = Math.max(0, minimumSplashMs - (performance.now() - startedAt));
  window.setTimeout(() => window.location.replace('/admin-panel/login/?pwa_ready=1'), remaining);
})();