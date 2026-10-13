document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('checkoutForm');
  const methodInput = document.getElementById('paymentMethod');
  const methodButtons = Array.from(document.querySelectorAll('[data-payment-method]'));
  const panels = Array.from(document.querySelectorAll('[data-payment-panel]'));
  if (!form || !methodInput || !methodButtons.length) return;

  const paymentFields = {
    banco: form.querySelector('[name="banco"]'),
    cedula: form.querySelector('[name="cedula_pagador"]'),
    referencia: form.querySelector('[name="referencia"]'),
    capture: form.querySelector('[name="capture"]')
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
    alert.textContent = 'Por favor complete todos los datos del Pago Móvil y adjunte su comprobante.';
    alert.scrollIntoView({behavior: 'smooth', block: 'center'});
  }

  function syncCsrfToken() {
    const csrfInput = form.querySelector('input[name="csrfmiddlewaretoken"]');
    const csrfCookie = document.cookie.split('; ').find(function (cookie) { return cookie.startsWith('csrftoken='); });
    if (csrfInput && csrfCookie) csrfInput.value = decodeURIComponent(csrfCookie.substring('csrftoken='.length));
  }

  function setPaymentMethod(method) {
    methodInput.value = method;
    methodButtons.forEach(function (button) {
      const selected = button.dataset.paymentMethod === method;
      button.classList.toggle('is-selected', selected);
      button.setAttribute('aria-selected', selected ? 'true' : 'false');
    });
    panels.forEach(function (panel) {
      const visible = panel.dataset.paymentPanel === method;
      panel.classList.toggle('is-visible', visible);
      panel.style.display = visible ? 'block' : 'none';
      panel.querySelectorAll('input, select').forEach(function (field) { field.disabled = !visible; });
    });
    Object.values(paymentFields).forEach(function (field) { if (field) field.required = method === 'PAGO_MOVIL'; });
  }

  methodButtons.forEach(function (button) {
    button.addEventListener('click', function () { setPaymentMethod(button.dataset.paymentMethod); });
  });

  form.addEventListener('submit', function (event) {
    syncCsrfToken();
    const mobilePayment = methodInput.value === 'PAGO_MOVIL';
    const missing = mobilePayment && Object.values(paymentFields).some(function (field) {
      if (!field) return true;
      return field.type === 'file' ? !field.files.length : !field.value.trim();
    });
    if (missing || !form.checkValidity()) {
      event.preventDefault();
      if (missing) showPaymentError();
      else form.reportValidity();
    }
  });

  setPaymentMethod(methodInput.value || 'PAGO_MOVIL');
});
