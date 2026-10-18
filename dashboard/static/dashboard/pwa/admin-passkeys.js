(() => {
  const registrationButton = document.getElementById('admin-register-passkey');
  const revokeButton = document.getElementById('admin-revoke-passkeys');
  const status = document.getElementById('admin-passkey-status');
  const recoveryStatus = document.getElementById('admin-recovery-passkey-status');
  const recoveryForm = document.getElementById('admin-recovery-form');
  const recoveryEmail = document.getElementById('rx-email');
  const loginForm = document.querySelector('.login-form');
  const usernameInput = document.getElementById('username');
  const usernameField = document.getElementById('admin-username-field');
  const passwordField = document.getElementById('password');
  const loginTitle = document.getElementById('admin-login-title');
  const knownAdminGreeting = document.getElementById('known-admin-greeting');
  const knownAdminName = document.getElementById('known-admin-name');
  const switchAdminButton = document.getElementById('switch-admin-account');
  const rememberDevice = document.querySelector('.remember-device');
  const biometricLoginButton = document.getElementById('admin-passkey-login');
  const installedPwa = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  const appSessionKey = 'ferreelectri_admin_app_session';
  const identityStorageKey = 'ferreelectri_admin_identity';

  function showRememberedAdmin() {
    if (!usernameInput || !usernameField || !knownAdminGreeting || !knownAdminName) return;
    try {
      const identity = JSON.parse(localStorage.getItem(identityStorageKey) || 'null');
      if (!identity || typeof identity.username !== 'string' || !identity.username) return;
      usernameInput.value = identity.username;
      usernameInput.required = false;
      usernameField.hidden = true;
      if (loginTitle) loginTitle.hidden = true;
      knownAdminName.textContent = identity.displayName || identity.username;
      knownAdminGreeting.hidden = false;
      if (rememberDevice) rememberDevice.hidden = true;
    } catch (error) {
      localStorage.removeItem(identityStorageKey);
    }
  }

  switchAdminButton?.addEventListener('click', () => {
    localStorage.removeItem(identityStorageKey);
    knownAdminGreeting.hidden = true;
    if (loginTitle) loginTitle.hidden = false;
    usernameField.hidden = false;
    usernameInput.value = '';
    usernameInput.required = true;
    if (rememberDevice) rememberDevice.hidden = false;
    usernameInput.focus();
  });

  function showStatus(message) {
    if (status) status.textContent = message;
    if (recoveryStatus) recoveryStatus.textContent = message;
  }

  function fromBase64Url(value) {
    const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4);
    const binary = atob(padded);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0)).buffer;
  }

  function toBase64Url(buffer) {
    let binary = '';
    for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  }

  function readCookie(name) {
    const prefix = `${name}=`;
    const value = document.cookie.split('; ').find((cookie) => cookie.startsWith(prefix));
    return value ? decodeURIComponent(value.slice(prefix.length)) : '';
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

  function credentialToJson(credential) {
    const response = credential.response;
    const result = {
      id: credential.id,
      rawId: toBase64Url(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: toBase64Url(response.clientDataJSON),
      },
      clientExtensionResults: credential.getClientExtensionResults(),
    };
    if ('attestationObject' in response) {
      result.response.attestationObject = toBase64Url(response.attestationObject);
      result.response.transports = response.getTransports?.() || [];
    }
    if ('authenticatorData' in response) result.response.authenticatorData = toBase64Url(response.authenticatorData);
    if ('signature' in response) result.response.signature = toBase64Url(response.signature);
    if (response.userHandle) result.response.userHandle = toBase64Url(response.userHandle);
    return result;
  }

  function prepareCreationOptions(options) {
    options.challenge = fromBase64Url(options.challenge);
    options.user.id = fromBase64Url(options.user.id);
    options.excludeCredentials = (options.excludeCredentials || []).map((item) => ({
      ...item,
      id: fromBase64Url(item.id),
    }));
    return options;
  }

  function prepareRequestOptions(options) {
    options.challenge = fromBase64Url(options.challenge);
    options.allowCredentials = (options.allowCredentials || []).map((item) => ({
      ...item,
      id: fromBase64Url(item.id),
    }));
    return options;
  }

  function explainError(error) {
    if (error.name === 'NotAllowedError') return 'Se canceló la operación o el dispositivo no encontró una llave registrada.';
    if (error.name === 'SecurityError') return 'El dominio HTTPS no coincide con el dominio de la llave. Revisa ADMIN_WEBAUTHN_RP_ID.';
    if (error.name === 'InvalidStateError') return 'Esta llave ya está registrada para este sitio en el dispositivo.';
    if (error.message === 'No hay llaves de acceso registradas para esta cuenta.') return 'Esta cuenta todavía no tiene una llave de acceso registrada.';
    if (error.message === 'passkey_not_registered') return 'Esta cuenta no tiene una llave de acceso registrada. Contacta al administrador para recuperar el acceso.';
    if (error.message === 'Escribe tu usuario o correo para usar la llave de acceso.') return 'Escribe tu usuario o correo para identificar la cuenta.';
    return 'No se pudo completar la operación con la llave de acceso. Inténtalo nuevamente.';
  }

  loginForm?.addEventListener('submit', () => {
    if (installedPwa) sessionStorage.setItem(appSessionKey, '1');
  });

  recoveryForm?.addEventListener('submit', async (event) => {
    if (recoveryForm.dataset.passkeyComplete === 'true') {
      delete recoveryForm.dataset.passkeyComplete;
      return;
    }
    event.preventDefault();
    const email = recoveryEmail?.value.trim().toLowerCase() || '';
    const submitButton = recoveryForm.querySelector('[type="submit"]');
    if (!email) {
      showStatus('Escribe el correo de la cuenta administrativa.');
      recoveryEmail?.focus();
      return;
    }
    if (submitButton) submitButton.disabled = true;
    showStatus('Verificando la huella registrada…');
    try {
      const options = await postJson('/admin-panel/passkeys/recovery/options/', { email });
      if (!window.PublicKeyCredential || !navigator.credentials?.get) {
        throw new Error('Este dispositivo no admite verificación biométrica para esta cuenta.');
      }
      const credential = await navigator.credentials.get({ publicKey: prepareRequestOptions(options) });
      if (!credential) throw new Error('No se recibió la confirmación del dispositivo.');
      await postJson('/admin-panel/passkeys/recovery/verify/', {
        email,
        credential: credentialToJson(credential),
      });
      showStatus('Huella verificada. Enviando el código al correo…');
      recoveryForm.dataset.passkeyComplete = 'true';
      if (submitButton) submitButton.disabled = false;
      recoveryForm.requestSubmit(submitButton || undefined);
    } catch (error) {
      showStatus(explainError(error));
    } finally {
      if (submitButton) submitButton.disabled = false;
    }
  });

  async function finishPasskeyLogin(credential) {
    if (!credential) return;
    const result = await postJson('/admin-panel/passkeys/login/verify/', { credential: credentialToJson(credential) });
    if (result.approval_required) {
      await window.waitForAdminLoginApproval(result.approval_id);
      return;
    }
    if (installedPwa) sessionStorage.setItem(appSessionKey, '1');
    if (typeof window.showAdminLoginSuccess === 'function') {
      await window.showAdminLoginSuccess(result.next || '/admin-panel/dashboard/');
      return;
    }
    const loader = document.getElementById('loader');
    if (loader) {
      loader.classList.add('is-biometric');
      loader.style.display = 'flex';
      const label = loader.querySelector('.loader-label');
      if (label) label.textContent = 'Acceso verificado. Desbloqueando…';
      requestAnimationFrame(() => loader.classList.add('is-unlocking'));
      await new Promise((resolve) => window.setTimeout(resolve, 520));
    }
    window.location.assign(result.next || '/admin-panel/dashboard/');
  }

  async function loginWithPasskey(button, hints = []) {
    if (!window.PublicKeyCredential || !navigator.credentials?.get) {
      showStatus('Este navegador no admite llaves de acceso para este sitio. Usa tu contraseña.');
      return;
    }
    button.disabled = true;
    try {
      const options = await postJson('/admin-panel/passkeys/login/options/', {
        username: usernameInput?.value.trim() || '',
      });
      if (hints.length) options.hints = hints;
      const credential = await navigator.credentials.get({ publicKey: prepareRequestOptions(options) });
      await finishPasskeyLogin(credential);
    } catch (error) {
      showStatus(explainError(error));
    } finally {
      button.disabled = false;
    }
  }

  biometricLoginButton?.addEventListener('click', () => loginWithPasskey(biometricLoginButton, ['client-device']));

  registrationButton?.addEventListener('click', async () => {
    if (!window.PublicKeyCredential || !navigator.credentials) {
      showStatus('Este navegador no admite llaves de acceso. Puedes seguir usando tu contraseña.');
      return;
    }
    registrationButton.disabled = true;
    try {
      const defaultDeviceName = /android|iphone|ipad|ipod/i.test(navigator.userAgent) ? 'Teléfono administrativo' : 'Equipo administrativo';
      const deviceName = window.prompt('Asigna un nombre para identificar este dispositivo:', defaultDeviceName);
      if (!deviceName?.trim()) return;
      const options = await postJson('/admin-panel/passkeys/register/options/', {});
      const credential = await navigator.credentials.create({ publicKey: prepareCreationOptions(options) });
      if (!credential) throw new Error('El dispositivo no devolvió una llave.');
      await postJson('/admin-panel/passkeys/register/verify/', {
        credential: credentialToJson(credential),
        name: deviceName.trim().slice(0, 80),
      });
      showStatus(`Llave registrada como “${deviceName.trim().slice(0, 80)}”. Usa la huella, rostro o PIN de este dispositivo en el próximo acceso.`);
    } catch (error) {
      showStatus(explainError(error));
    } finally {
      registrationButton.disabled = false;
    }
  });

  revokeButton?.addEventListener('click', async () => {
    if (!window.confirm('¿Revocar todas las llaves de acceso de esta cuenta? La contraseña seguirá disponible.')) return;
    revokeButton.disabled = true;
    try {
      const result = await postJson('/admin-panel/passkeys/revoke-all/', {});
      showStatus(`Se revocaron ${result.revoked} llaves. La contraseña sigue activa.`);
    } catch (error) {
      showStatus(explainError(error));
    } finally {
      revokeButton.disabled = false;
    }
  });

  showRememberedAdmin();
})();
