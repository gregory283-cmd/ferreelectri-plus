(() => {
  const installButton = document.getElementById('admin-install-app');
  const pushButton = document.getElementById('admin-enable-push');
  const status = document.getElementById('admin-pwa-status');
  let installPrompt = null;
  let serviceWorkerRegistration = null;

  function showStatus(message) {
    if (status) status.textContent = message;
  }

  function readCookie(name) {
    const prefix = `${name}=`;
    const value = document.cookie.split('; ').find((cookie) => cookie.startsWith(prefix));
    return value ? decodeURIComponent(value.slice(prefix.length)) : '';
  }

  function decodeVapidKey(encodedKey) {
    const padding = '='.repeat((4 - encodedKey.length % 4) % 4);
    const base64 = (encodedKey + padding).replace(/-/g, '+').replace(/_/g, '/');
    return Uint8Array.from(atob(base64), (character) => character.charCodeAt(0));
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': readCookie('csrftoken'),
      },
      body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || 'request_failed');
    return result;
  }

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/service-worker.js', { scope: '/' })
      .then((registration) => { serviceWorkerRegistration = registration; })
      .catch(() => showStatus('No se pudo preparar la aplicación en este navegador.'));
  }

  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches
    || navigator.standalone === true;
  if (isIos && !isStandalone && installButton) installButton.hidden = false;

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    installPrompt = event;
    if (installButton) installButton.hidden = false;
  });

  window.addEventListener('appinstalled', () => {
    installPrompt = null;
    if (installButton) installButton.hidden = true;
    showStatus('Aplicación instalada.');
  });

  installButton?.addEventListener('click', async () => {
    if (!installPrompt) {
      showStatus('En iPhone, usa Compartir y luego Añadir a pantalla de inicio.');
      return;
    }
    installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = null;
    installButton.hidden = true;
  });

  pushButton?.addEventListener('click', async () => {
    const publicKey = pushButton.dataset.vapidPublicKey || '';
    if (!publicKey) {
      showStatus('Las notificaciones aún no están configuradas en el servidor.');
      return;
    }
    if (!('PushManager' in window) || !('Notification' in window)) {
      showStatus('Este navegador no admite notificaciones push.');
      return;
    }

    try {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        showStatus('No se activaron las notificaciones. Puedes cambiar el permiso en el navegador.');
        return;
      }
      serviceWorkerRegistration = serviceWorkerRegistration || await navigator.serviceWorker.ready;
      let subscription = await serviceWorkerRegistration.pushManager.getSubscription();
      if (!subscription) {
        subscription = await serviceWorkerRegistration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: decodeVapidKey(publicKey),
        });
      }
      await postJson('/admin-panel/push/subscribe/', subscription.toJSON());
      showStatus('Notificaciones de pedidos activadas para este dispositivo.');
    } catch (error) {
      showStatus(error.message === 'push_not_configured'
        ? 'Las claves de notificación aún no están configuradas en el servidor.'
        : 'No se pudieron activar las notificaciones. Inténtalo de nuevo.');
    }
  });
})();
