(() => {
  const form = document.getElementById('checkoutForm');
  const methodInput = document.getElementById('paymentMethod');
  const methodButtons = document.querySelectorAll('[data-payment-method]');
  const panels = document.querySelectorAll('[data-payment-panel]');
  const paymentFields = form ? {
    banco: form.querySelector('[name="banco"]'),
    cedula: form.querySelector('[name="cedula_pagador"]'),
    referencia: form.querySelector('[data-payment-panel="PAGO_MOVIL"] [name="referencia"]'),
    capture: form.querySelector('[name="capture"]')
  } : {};
  const requiredFields = {
    PAGO_MOVIL: ['banco', 'cedula', 'referencia', 'capture'],
  };

  function showPaymentError() {
    let alert = document.getElementById('paymentValidationAlert');
    if (!alert) {
      alert = document.createElement('div');
      alert.id = 'paymentValidationAlert';
      alert.setAttribute('role', 'alert');
      alert.className = 'mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700';
      form.prepend(alert);
    }
    alert.textContent = 'Por favor completa el banco, la cédula, la referencia y adjunta el comprobante de Pago Móvil.';
    alert.scrollIntoView({behavior: 'smooth', block: 'center'});
  }

  function syncCsrfToken() {
    const csrfInput = form.querySelector('input[name="csrfmiddlewaretoken"]');
    const csrfCookie = document.cookie.split('; ').find((cookie) => cookie.startsWith('csrftoken='));
    if (csrfInput && csrfCookie) csrfInput.value = decodeURIComponent(csrfCookie.substring('csrftoken='.length));
  }

  function setPaymentMethod(method) {
    if (!methodInput) return;
    methodInput.value = method;
    const submitButton = form?.querySelector('[type="submit"]');
    if (submitButton) submitButton.disabled = !method;
    methodButtons.forEach((button) => {
      const selected = button.dataset.paymentMethod === method;
      button.classList.toggle('is-selected', selected);
      button.setAttribute('aria-selected', selected ? 'true' : 'false');
    });
    panels.forEach((panel) => {
      const visible = panel.dataset.paymentPanel === method;
      panel.classList.toggle('is-visible', visible);
      panel.querySelectorAll('input, select').forEach((field) => {
        field.disabled = !visible;
      });
    });
    const required = new Set(requiredFields[method] || []);
    Object.entries(paymentFields).forEach(([name, field]) => {
      if (!field) return;
      field.required = required.has(name);
    });
  }

  methodButtons.forEach((button) => {
    button.addEventListener('click', () => setPaymentMethod(button.dataset.paymentMethod));
  });

  form?.addEventListener('submit', (event) => {
    syncCsrfToken();
    const activeFields = requiredFields[methodInput?.value] || [];
    const missingPaymentData = activeFields.some((fieldName) => {
      const field = paymentFields[fieldName];
      if (!field) return true;
      return field.type === 'file' ? !field.files?.length : !field.value.trim();
    });
    if (missingPaymentData) {
      event.preventDefault();
      showPaymentError();
      return;
    }
    if (!form.checkValidity()) {
      event.preventDefault();
      form.reportValidity();
    }
  });

  setPaymentMethod(methodInput?.value || '');
})();
