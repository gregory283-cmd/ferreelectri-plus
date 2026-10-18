(() => {
  const registrationButton = document.getElementById('admin-register-passkey');
  const revokeButton = document.getElementById('admin-revoke-passkeys');
  const status = document.getElementById('admin-passkey-status');
  const loginForm = document.querySelector('.login-form');
  const usernameInput = document.getElementById('username');
  const installedPwa = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  const appSessionKey = 'ferreelectri_admin_app_session';

  function showStatus(message) {
    if (status) status.textContent = message;
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
    if (error.message === 'No hay llaves de acceso registradas.') return 'Todavía no hay llaves de acceso registradas para el personal administrativo.';
    return 'No se pudo completar la operación con la llave de acceso. Inténtalo nuevamente.';
  }

  loginForm?.addEventListener('submit', () => {
    if (installedPwa) sessionStorage.setItem(appSessionKey, '1');
  });

  async function finishPasskeyLogin(credential) {
    if (!credential) return;
    const result = await postJson('/admin-panel/passkeys/login/verify/', { credential: credentialToJson(credential) });
    if (installedPwa) sessionStorage.setItem(appSessionKey, '1');
    window.location.assign(result.next || '/admin-panel/dashboard/');
  }

  async function startConditionalPasskeyLogin() {
    if (!usernameInput || !window.PublicKeyCredential || !navigator.credentials?.get) return;
    try {
      const available = await window.PublicKeyCredential.isConditionalMediationAvailable?.();
      if (!available) return;
      const options = await postJson('/admin-panel/passkeys/login/options/', {});
      const credential = await navigator.credentials.get({
        publicKey: prepareRequestOptions(options),
        mediation: 'conditional',
      });
      await finishPasskeyLogin(credential);
    } catch (error) {
      if (error.name !== 'NotAllowedError' && error.name !== 'AbortError') showStatus(explainError(error));
    }
  }

  registrationButton?.addEventListener('click', async () => {
    if (!window.PublicKeyCredential || !navigator.credentials) {
      showStatus('Este navegador no admite llaves de acceso. Puedes seguir usando tu contraseña.');
      return;
    }
    registrationButton.disabled = true;
    try {
      const options = await postJson('/admin-panel/passkeys/register/options/', {});
      const credential = await navigator.credentials.create({ publicKey: prepareCreationOptions(options) });
      if (!credential) throw new Error('El dispositivo no devolvió una llave.');
      await postJson('/admin-panel/passkeys/register/verify/', { credential: credentialToJson(credential) });
      showStatus('Llave registrada. Usa la huella, rostro o PIN de tu dispositivo en el próximo acceso.');
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

  startConditionalPasskeyLogin();
})();
