(() => {
  const installButton = document.getElementById('admin-install-app');
  const pushButton = document.getElementById('admin-enable-push');
  const status = document.getElementById('admin-pwa-status');
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches
    || navigator.standalone === true;
  const isNamingDevice = Boolean(document.querySelector('.admin-device-name-page'));
  const appSessionKey = 'ferreelectri_admin_app_session';
  const lastActivityKey = 'ferreelectri_admin_last_activity';
  const internalNavigationKey = 'ferreelectri_admin_internal_navigation_at';
  const appExitPendingKey = 'ferreelectri_admin_exit_pending';
  const appSessionReturnAllowedKey = 'ferreelectri_admin_return_allowed';
  let installPrompt = null;
  let serviceWorkerRegistration = null;

  const authenticatedIdentity = document.getElementById('admin-auth-identity');
  if (authenticatedIdentity) {
    try {
      localStorage.setItem('ferreelectri_admin_identity', JSON.stringify({
        username: authenticatedIdentity.dataset.username,
        displayName: authenticatedIdentity.dataset.displayName,
      }));
      if (isStandalone) sessionStorage.setItem(appSessionKey, '1');
    } catch (error) {
      // El login por contraseña sigue disponible si el navegador bloquea el almacenamiento local.
    }
  }

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

  async function postJson(url, payload, keepalive = false) {
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      keepalive,
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

  const approvalDialog = document.getElementById('admin-login-approval-dialog');
  const approvalDetails = document.getElementById('admin-login-approval-details');
  const approvalStatus = document.getElementById('admin-login-approval-status');
  const approveLoginButton = document.getElementById('admin-approval-accept');
  const denyLoginButton = document.getElementById('admin-approval-deny');
  let currentApprovalId = '';
  let approvalPollInProgress = false;

  async function checkPendingAdminLogin() {
    if (!authenticatedIdentity || !approvalDialog || approvalDialog.open || approvalPollInProgress
      || document.visibilityState !== 'visible') return;
    approvalPollInProgress = true;
    try {
      const response = await fetch('/admin-panel/session-approval/pending/', {
        credentials: 'same-origin',
        headers: { 'Accept': 'application/json' },
      });
      if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) {
        window.location.replace('/admin-panel/login/');
        return;
      }
      if (!response.ok) return;
      const result = await response.json();
      const approval = result.approvals?.[0];
      if (!approval) return;
      currentApprovalId = approval.id;
      approvalDetails.textContent = `${approval.username} intenta registrar un dispositivo. IP: ${approval.ip_address}. Navegador: ${approval.user_agent}. Si apruebas, el nuevo equipo se agregará a la cuenta; esta sesión permanecerá abierta.`;
      approvalStatus.textContent = 'La solicitud vence en dos minutos.';
      approveLoginButton.disabled = false;
      denyLoginButton.disabled = false;
      approvalDialog.showModal();
    } catch (error) {
      // A temporary network error should not interrupt the active session.
    } finally {
      approvalPollInProgress = false;
    }
  }

  async function respondToAdminLogin(decision) {
    if (!currentApprovalId) return;
    approveLoginButton.disabled = true;
    denyLoginButton.disabled = true;
    approvalStatus.textContent = decision === 'approve' ? 'Aprobando y transfiriendo la sesión…' : 'Denegando el acceso…';
    try {
      await postJson(`/admin-panel/session-approval/${encodeURIComponent(currentApprovalId)}/respond/`, { decision });
      currentApprovalId = '';
      approvalDialog.close();
    } catch (error) {
      approvalStatus.textContent = 'No se pudo guardar la decisión. Comprueba la conexión e inténtalo de nuevo.';
      approveLoginButton.disabled = false;
      denyLoginButton.disabled = false;
    }
  }

  approveLoginButton?.addEventListener('click', () => respondToAdminLogin('approve'));
  denyLoginButton?.addEventListener('click', () => respondToAdminLogin('deny'));
  if (authenticatedIdentity && approvalDialog) {
    window.setInterval(checkPendingAdminLogin, 5000);
    document.addEventListener('visibilitychange', checkPendingAdminLogin);
  }

  async function lockAdminSession() {
    try {
      sessionStorage.removeItem(appSessionKey);
    } catch (error) {
      // Continue to revoke the server session even if browser storage is unavailable.
    }
    try {
      const result = await postJson('/admin-panel/app-session/lock/', {}, true);
      return result.ok === true;
    } catch (error) {
      showStatus('No se pudo cerrar la sesión de la aplicación. Comprueba tu conexión e inténtalo de nuevo.');
    }
    return false;
  }

  let appExitPending = false;
  let appExitLockStarted = false;

  function markInternalNavigation() {
    try {
      sessionStorage.setItem(internalNavigationKey, String(Date.now()));
    } catch (error) {
      // Navigation can still continue if storage is unavailable.
    }
  }

  function clearAppExitMarkers() {
    appExitPending = false;
    try {
      sessionStorage.removeItem(appExitPendingKey);
      sessionStorage.removeItem(internalNavigationKey);
      sessionStorage.removeItem(appSessionReturnAllowedKey);
    } catch (error) {
      // In-memory exit state is enough for the current page.
    }
  }

  function startStandaloneExit() {
    if (!isStandalone || isNamingDevice || appExitLockStarted) return;
    appExitPending = true;
    try {
      sessionStorage.setItem(appExitPendingKey, '1');
    } catch (error) {
      // Defer logout until the current document resumes.
    }
  }

  function finishStandaloneExit() {
    if (!isStandalone || isNamingDevice || appExitLockStarted) return;
    appExitLockStarted = true;
    lockAdminSession().then((locked) => {
      if (locked) {
        clearAppExitMarkers();
        window.location.replace('/admin-panel/app-launch/');
        return;
      }
      appExitLockStarted = false;
      appExitPending = true;
      try {
        sessionStorage.setItem(appExitPendingKey, '1');
      } catch (error) {
        // A later visibility change can retry from the in-memory flag.
      }
    });
  }

  function resolveStandaloneExit(sameDocumentResume = false) {
    if (!isStandalone || isNamingDevice) return;
    let pending = appExitPending;
    let internalNavigation = false;
    let appReturnAllowed = false;
    try {
      pending = pending || sessionStorage.getItem(appExitPendingKey) === '1';
      const timestamp = Number(sessionStorage.getItem(internalNavigationKey));
      internalNavigation = Boolean(timestamp && Date.now() - timestamp < 15000);
      appReturnAllowed = sessionStorage.getItem(appSessionReturnAllowedKey) === '1';
    } catch (error) {
      // The in-memory flag still handles a background/foreground cycle.
    }
    if (!pending) return;

    const navigationType = performance.getEntriesByType('navigation')[0]?.type;
    if (sameDocumentResume || navigationType === 'reload' || internalNavigation || appReturnAllowed) {
      clearAppExitMarkers();
      return;
    }
    finishStandaloneExit();
  }

  if (isStandalone && !isNamingDevice) {
    document.addEventListener('click', (event) => {
      const link = event.target.closest('a[href]');
      if (!link || link.target === '_blank' || event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.hasAttribute('download')) return;
      const destination = new URL(link.href, window.location.href);
      if (destination.origin === window.location.origin && destination.href !== window.location.href) {
        markInternalNavigation();
        if (link.hasAttribute('data-admin-session-continue')) {
          try {
            sessionStorage.setItem(appSessionReturnAllowedKey, '1');
          } catch (error) {
            // The immediate internal-navigation marker remains the fallback.
          }
        }
      }
    }, true);
    document.addEventListener('submit', (event) => {
      const form = event.target;
      const destination = new URL(form.action || window.location.href, window.location.href);
      if (destination.origin === window.location.origin) markInternalNavigation();
    }, true);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') startStandaloneExit();
      else resolveStandaloneExit(true);
    });
    window.addEventListener('pagehide', startStandaloneExit);
    window.addEventListener('pageshow', () => resolveStandaloneExit());
  }

  const sessionDialog = document.getElementById('admin-session-dialog');
  const sessionDialogTitle = document.getElementById('admin-session-title');
  const sessionDialogMessage = document.getElementById('admin-session-message');
  const sessionCountdown = document.getElementById('admin-session-countdown');
  const sessionStatus = document.getElementById('admin-session-status');
  const continueSessionButton = document.getElementById('admin-session-continue');
  const closeSessionButton = document.getElementById('admin-session-close');
  const dashboardUrl = authenticatedIdentity?.dataset.dashboardUrl || '/admin-panel/dashboard/';
  const loginUrl = authenticatedIdentity?.dataset.loginUrl || '/admin-panel/login/';
  const dashboardPath = new URL(dashboardUrl, window.location.origin).pathname.replace(/\/+$/, '');
  const isDashboard = window.location.pathname.replace(/\/+$/, '') === dashboardPath;
  const idleTimeoutMs = 2 * 60 * 1000;
  const confirmationTimeoutMs = 30 * 1000;
  let idleTimeout = null;
  let confirmationInterval = null;
  let confirmationDeadline = 0;
  let confirmationReason = '';
  let logoutInProgress = false;
  let activityPersistTimeout = null;
  let lastActivityPersistedAt = 0;
  let lastActivityAt = Date.now();
  try {
    lastActivityAt = Number(sessionStorage.getItem(lastActivityKey)) || lastActivityAt;
  } catch (error) {
    // The in-memory idle timer remains active if browser storage is unavailable.
  }

  function saveLastActivity(timestamp) {
    lastActivityAt = timestamp;
    try {
      sessionStorage.setItem(lastActivityKey, String(timestamp));
    } catch (error) {
      // In-memory idle tracking remains active if session storage is unavailable.
    }
  }

  function clearConfirmationInterval() {
    if (confirmationInterval) window.clearInterval(confirmationInterval);
    confirmationInterval = null;
  }

  function beginSessionLogout() {
    if (logoutInProgress) return;
    logoutInProgress = true;
    clearConfirmationInterval();
    if (continueSessionButton) continueSessionButton.disabled = true;
    if (closeSessionButton) closeSessionButton.disabled = true;
    lockAdminSession().then((locked) => {
      if (locked) {
        try {
          sessionStorage.removeItem(lastActivityKey);
        } catch (error) {
          // Server-side logout remains authoritative if browser storage is unavailable.
        }
        window.location.replace(loginUrl);
        return;
      }
      logoutInProgress = false;
      if (continueSessionButton) continueSessionButton.disabled = false;
      if (closeSessionButton) closeSessionButton.disabled = false;
      if (sessionStatus) sessionStatus.textContent = 'No se pudo cerrar la sesión por falta de conexión. Se volverá a intentar.';
      confirmationDeadline = Date.now() + 5000;
      confirmationInterval = window.setInterval(updateConfirmationCountdown, 1000);
    });
  }

  function updateConfirmationCountdown() {
    const secondsRemaining = Math.max(0, Math.ceil((confirmationDeadline - Date.now()) / 1000));
    if (sessionCountdown) sessionCountdown.textContent = `Cierre de sesión en ${secondsRemaining} s`;
    if (!secondsRemaining) beginSessionLogout();
  }

  function showSessionConfirmation(reason) {
    if (!sessionDialog || sessionDialog.open || logoutInProgress) return;
    confirmationReason = reason;
    confirmationDeadline = Date.now() + confirmationTimeoutMs;
    if (sessionDialogTitle) sessionDialogTitle.textContent = reason === 'idle' ? '¿Sigues ahí?' : '¿Quieres salir del panel?';
    if (sessionDialogMessage) {
      sessionDialogMessage.textContent = reason === 'idle'
        ? 'Tu sesión se cerrará por inactividad. ¿Quieres continuar trabajando?'
        : 'Si no eliges una opción, se cerrará tu sesión automáticamente.';
    }
    if (continueSessionButton) {
      continueSessionButton.hidden = false;
      continueSessionButton.textContent = reason === 'idle' ? 'Seguir trabajando' : 'Cancelar';
    }
    if (sessionStatus) sessionStatus.textContent = '';
    sessionDialog.showModal();
    updateConfirmationCountdown();
    clearConfirmationInterval();
    confirmationInterval = window.setInterval(updateConfirmationCountdown, 1000);
  }

  function continueWorking() {
    if (sessionDialog?.open) sessionDialog.close();
    clearConfirmationInterval();
    confirmationReason = '';
    saveLastActivity(Date.now());
    scheduleIdleConfirmation();
  }

  function scheduleIdleConfirmation() {
    if (isStandalone || isNamingDevice) return;
    if (idleTimeout) window.clearTimeout(idleTimeout);
    if (!sessionDialog || sessionDialog.open || logoutInProgress) return;
    const remaining = idleTimeoutMs - (Date.now() - lastActivityAt);
    if (remaining <= 0) {
      showSessionConfirmation('idle');
      return;
    }
    idleTimeout = window.setTimeout(scheduleIdleConfirmation, remaining);
  }

  function recordActivity() {
    if (sessionDialog?.open || logoutInProgress) return;
    lastActivityAt = Date.now();
    if (activityPersistTimeout) return;
    const delay = Math.max(0, 1000 - (lastActivityAt - lastActivityPersistedAt));
    activityPersistTimeout = window.setTimeout(() => {
      activityPersistTimeout = null;
      saveLastActivity(lastActivityAt);
      lastActivityPersistedAt = lastActivityAt;
    }, delay);
  }

  continueSessionButton?.addEventListener('click', continueWorking);
  closeSessionButton?.addEventListener('click', beginSessionLogout);
  sessionDialog?.addEventListener('cancel', (event) => {
    event.preventDefault();
    if (confirmationReason === 'exit') continueWorking();
  });

  if (sessionDialog) {
    history.replaceState({ adminSessionBase: true }, '', window.location.href);
    history.pushState({ adminSessionGuard: true }, '', window.location.href);
    window.addEventListener('popstate', () => {
      if (isDashboard) {
        history.pushState({ adminSessionGuard: true }, '', dashboardUrl);
        showSessionConfirmation('exit');
        return;
      }
      markInternalNavigation();
      window.location.replace(dashboardUrl);
    });
  }

  ['pointerdown', 'keydown', 'input', 'scroll', 'touchstart'].forEach((eventName) => {
    document.addEventListener(eventName, recordActivity, { passive: eventName === 'scroll' || eventName === 'touchstart' });
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') scheduleIdleConfirmation();
  });
  scheduleIdleConfirmation();

  function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    navigator.serviceWorker.register('/service-worker.js', { scope: '/' })
      .then((registration) => { serviceWorkerRegistration = registration; })
      .catch(() => showStatus('No se pudo preparar la aplicación en este navegador.'));
  }

  window.requestAnimationFrame(() => window.requestAnimationFrame(registerServiceWorker));

  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
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
