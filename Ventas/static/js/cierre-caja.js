document.addEventListener('DOMContentLoaded', () => {
  const button = document.getElementById('btn-generar-reporte');
  const modal = document.getElementById('modal-filtros-reporte');
  const closeButton = document.getElementById('cerrar-modal-reporte');
  const form = document.getElementById('form-filtros-reporte');
  const customerInput = document.getElementById('filtro-cliente');
  const suggestions = document.getElementById('sugerencias-clientes');

  if (button && modal) button.addEventListener('click', () => { modal.style.display = 'flex'; });
  if (closeButton && modal) closeButton.addEventListener('click', () => { modal.style.display = 'none'; });
  if (modal) {
    modal.addEventListener('click', (event) => {
      if (event.target === modal) modal.style.display = 'none';
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') modal.style.display = 'none';
    });
  }

  if (customerInput && suggestions) {
    let customers = [];
    fetch(customerInput.dataset.clientesUrl).then((response) => response.ok ? response.json() : []).then((data) => {
      customers = Array.isArray(data) ? data : [];
    }).catch(() => {});

    customerInput.addEventListener('input', () => {
      const query = customerInput.value.trim().toLocaleLowerCase('es');
      customerInput.dataset.cedula = '';
      suggestions.replaceChildren();
      if (!query) { suggestions.style.display = 'none'; return; }

      customers.filter((customer) => `${customer.nombre} ${customer.apellido} ${customer.cedula}`
        .toLocaleLowerCase('es').includes(query)).slice(0, 8).forEach((customer) => {
        const option = document.createElement('li');
        option.textContent = `${customer.nombre} ${customer.apellido} (${customer.cedula})`;
        option.addEventListener('click', () => {
          customerInput.value = option.textContent;
          customerInput.dataset.cedula = customer.cedula;
          suggestions.style.display = 'none';
        });
        suggestions.append(option);
      });
      suggestions.style.display = suggestions.childElementCount ? 'block' : 'none';
    });
    document.addEventListener('click', (event) => {
      if (!customerInput.contains(event.target) && !suggestions.contains(event.target)) suggestions.style.display = 'none';
    });
  }

  if (form) form.addEventListener('submit', (event) => {
    event.preventDefault();
    const start = document.getElementById('filtro-inicio')?.value;
    const end = document.getElementById('filtro-fin')?.value;
    if (!start || !end || start > end) {
      form.reportValidity();
      if (start && end && start > end) window.alert('La fecha inicial debe ser anterior o igual a la fecha final.');
      return;
    }
    const url = new URL(form.dataset.reportUrl, window.location.origin);
    url.searchParams.set('inicio', start);
    url.searchParams.set('fin', end);
    const customerId = customerInput?.dataset.cedula;
    if (customerId) url.searchParams.set('cliente', customerId);
    window.open(url.toString(), '_blank', 'noopener');
    if (modal) modal.style.display = 'none';
  });

  const canvas = document.getElementById('cash-channel-chart');
  const dataNode = document.getElementById('cash-chart-data');
  if (!canvas || !dataNode || typeof Chart === 'undefined') return;

  let data;
  try { data = JSON.parse(dataNode.textContent || '{}'); } catch (error) { return; }
  const styles = getComputedStyle(document.querySelector('.cierre-caja-main'));
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  new Chart(canvas, {
    type: 'bar',
    data: {
      labels: data.labels,
      datasets: [
        { label: 'E-commerce', data: data.ecommerce, backgroundColor: '#48c9df', borderRadius: 5, maxBarThickness: 32 },
        { label: 'Facturación manual', data: data.manual, backgroundColor: '#8ea8e8', borderRadius: 5, maxBarThickness: 32 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: reduceMotion ? false : { duration: 1000, easing: 'easeOutQuart' },
      animations: { y: { from: 0 } },
      interaction: { intersect: false, mode: 'index' },
      plugins: {
        legend: { position: 'bottom', labels: { color: styles.getPropertyValue('--cash-muted').trim(), usePointStyle: true, boxWidth: 8, padding: 16 } },
        tooltip: { callbacks: { label: (context) => `${context.dataset.label}: ${data.currency || ''} ${Number(context.parsed.y).toLocaleString('es-VE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` } },
      },
      scales: {
        x: { grid: { display: false }, border: { display: false }, ticks: { color: styles.getPropertyValue('--cash-muted').trim() } },
        y: { beginAtZero: true, grid: { color: styles.getPropertyValue('--cash-line').trim() }, border: { display: false }, ticks: { color: styles.getPropertyValue('--cash-muted').trim(), callback: (value) => Number(value).toLocaleString('es-VE', { notation: 'compact', maximumFractionDigits: 1 }) } },
      },
    },
  });
});