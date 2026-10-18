window.showAdminLoginSuccess = async function(destination) {
  const loader = document.getElementById('loader');
  if (!loader) {
    window.location.assign(destination);
    return;
  }
  loader.classList.add('is-biometric', 'is-success');
  loader.style.display = 'flex';
  const label = loader.querySelector('.loader-label');
  if (label) label.textContent = 'Acceso verificado. Bienvenido.';
  requestAnimationFrame(() => requestAnimationFrame(() => loader.classList.add('is-unlocking')));
  await new Promise((resolve) => window.setTimeout(resolve, 1050));
  window.location.assign(destination);
};

document.addEventListener('DOMContentLoaded', function() {
  const passwordInput = document.getElementById('password');
  const toggleEye = document.querySelector('.toggle-password');
  const loader = document.getElementById('loader');
  const form = document.querySelector('.login-form');
  const heroTitle = document.querySelector('.hero-title');
  const launchSplash = document.querySelector('.pwa-launch-splash');

  if (launchSplash && document.documentElement.classList.contains('pwa-launching')) {
    let splashDismissScheduled = false;
    const dismissSplash = () => {
      if (splashDismissScheduled) return;
      splashDismissScheduled = true;
      window.setTimeout(() => {
        launchSplash.classList.add('is-hiding');
        window.setTimeout(() => {
          launchSplash.remove();
          document.documentElement.classList.remove('pwa-launching');
        }, 450);
      }, 700);
    };
    if (document.readyState === 'complete') dismissSplash();
    else window.addEventListener('load', dismissSplash, { once: true });
    window.setTimeout(dismissSplash, 2200);
  }

  if (toggleEye && passwordInput) {
    toggleEye.addEventListener('click', function() {
      const isPassword = passwordInput.type === 'password';
      passwordInput.type = isPassword ? 'text' : 'password';
      const icon = toggleEye.querySelector('ion-icon');
      if (icon) icon.setAttribute('name', isPassword ? 'eye-off-outline' : 'eye-outline');
    });
  }

  if (form && loader) {
    form.addEventListener('submit', async function(event) {
      event.preventDefault();
      if (form.dataset.submitting === 'true') return;
      form.dataset.submitting = 'true';
      loader.style.display = 'flex';
      loader.classList.remove('is-biometric', 'is-success', 'is-unlocking');
      const loaderLabel = loader.querySelector('.loader-label');
      if (loaderLabel) loaderLabel.textContent = 'Verificando credenciales…';
      const status = document.getElementById('admin-passkey-status');
      if (status) {
        status.textContent = '';
        status.classList.remove('login-feedback-error');
      }
      try {
        const response = await fetch(form.action, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
          body: new FormData(form),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || !result.ok) {
          const messages = Object.values(result.errors || {}).flat();
          if (status) {
            status.textContent = messages.join(' ') || 'No se pudieron verificar las credenciales. Inténtalo de nuevo.';
            status.classList.add('login-feedback-error');
          }
          loader.style.display = 'none';
          delete form.dataset.submitting;
          return;
        }
        await window.showAdminLoginSuccess(result.next || '/admin-panel/dashboard/');
      } catch (error) {
        if (status) {
          status.textContent = 'No se pudo conectar. Revisa tu conexión e inténtalo de nuevo.';
          status.classList.add('login-feedback-error');
        }
        loader.style.display = 'none';
        delete form.dataset.submitting;
      }
    });
  }

  const validationModal = document.getElementById('validationModal');
  if (validationModal) {
    validationModal.classList.add('show');
    const closeButtons = validationModal.querySelectorAll('.modal-close, .modal-ok');
    closeButtons.forEach(function(button) {
      button.addEventListener('click', function() {
        validationModal.classList.remove('show');
      });
    });
    validationModal.addEventListener('click', function(event) {
      if (event.target === validationModal) {
        validationModal.classList.remove('show');
      }
    });
  }

  if (heroTitle && window.matchMedia('(max-width: 720px)').matches) {
    const titleLines = Array.from(heroTitle.querySelectorAll('.hero-title-line'));
    titleLines[0].textContent = '¡Bienvenido';
    titleLines[1].textContent = 'de nuevo!';
    titleLines[2].textContent = '';
  } else if (heroTitle) {
    const titleLines = Array.from(heroTitle.querySelectorAll('.hero-title-line'));
    const rotatingLine = heroTitle.querySelector('.rotating-line');
    const staticTexts = titleLines.slice(0, 2).map(function(line) {
      return line.textContent.trim();
    });
    const phrases = [
      'siguiente nivel',
      'control total',
      'éxito diario',
      'gestión sin límites',
      'máximo rendimiento'
    ];
    let currentLine = 0;
    let charIndex = 0;
    let deleting = false;
    let phraseIndex = 0;
    const typeSpeed = 40;
    const deleteSpeed = 24;
    const pauseAfterComplete = 3000;

    titleLines.forEach(function(line) {
      line.textContent = '';
    });

    const updateCursor = function() {
      titleLines.forEach(function(line, index) {
        line.classList.toggle('current', index === currentLine || (index === 2 && currentLine === 2));
      });
    };

    const typeLoop = function() {
      if (currentLine < 2) {
        const text = staticTexts[currentLine];
        updateCursor();
        if (charIndex < text.length) {
          titleLines[currentLine].textContent = text.slice(0, charIndex + 1);
          charIndex += 1;
          setTimeout(typeLoop, typeSpeed);
        } else {
          currentLine += 1;
          charIndex = 0;
          setTimeout(typeLoop, 120);
        }
        return;
      }

      if (!rotatingLine) return;
      const text = phrases[phraseIndex];
      updateCursor();

      if (!deleting) {
        if (charIndex < text.length) {
          rotatingLine.textContent = text.slice(0, charIndex + 1);
          charIndex += 1;
          setTimeout(typeLoop, typeSpeed);
        } else {
          setTimeout(function() {
            deleting = true;
            setTimeout(typeLoop, deleteSpeed);
          }, pauseAfterComplete);
        }
      } else {
        if (charIndex > 0) {
          rotatingLine.textContent = text.slice(0, charIndex - 1);
          charIndex -= 1;
          setTimeout(typeLoop, deleteSpeed);
        } else {
          deleting = false;
          phraseIndex = (phraseIndex + 1) % phrases.length;
          setTimeout(typeLoop, typeSpeed);
        }
      }
    };

    typeLoop();
  }
});
