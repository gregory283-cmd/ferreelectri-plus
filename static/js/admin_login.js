document.addEventListener('DOMContentLoaded', function() {
  const passwordInput = document.getElementById('password');
  const toggleEye = document.querySelector('.toggle-password');
  const loader = document.getElementById('loader');
  const form = document.querySelector('.login-form');
  const heroTitle = document.querySelector('.hero-title');

  if (toggleEye && passwordInput) {
    toggleEye.addEventListener('click', function() {
      const isPassword = passwordInput.type === 'password';
      passwordInput.type = isPassword ? 'text' : 'password';
      const icon = toggleEye.querySelector('ion-icon');
      if (icon) icon.setAttribute('name', isPassword ? 'eye-off-outline' : 'eye-outline');
    });
  }

  if (form && loader) {
    form.addEventListener('submit', function() {
      loader.style.display = 'flex';
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
