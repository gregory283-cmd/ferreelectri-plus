document.addEventListener('DOMContentLoaded', () => {
  const root = document.querySelector('.executive-report');
  if (!root) return;

  const form = document.querySelector('.report-filters');
  const start = form?.querySelector('input[name="inicio"]');
  const end = form?.querySelector('input[name="fin"]');
  form?.addEventListener('submit', (event) => {
    if (start?.value && end?.value && start.value > end.value) {
      event.preventDefault();
      end.setCustomValidity('La fecha final debe ser igual o posterior a la fecha inicial.');
      end.reportValidity();
    }
  });
  end?.addEventListener('input', () => end.setCustomValidity(''));

  if (typeof Chart === 'undefined') return;
  const parse = (id) => {
    const node = document.getElementById(id);
    try { return JSON.parse(node?.textContent || '[]'); } catch (error) { return []; }
  };
  const sales = parse('executive-sales-data');
  const products = parse('executive-products-data');
  const styles = getComputedStyle(root);
  const muted = styles.getPropertyValue('--report-muted').trim();
  const line = styles.getPropertyValue('--report-line').trim();
  const surface = styles.getPropertyValue('--report-surface').trim();
  const currency = root.dataset.currency || '';
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const motion = reduceMotion ? false : { duration: 900, easing: 'easeOutQuart' };

  const salesCanvas = document.getElementById('report-sales-chart');
  if (salesCanvas) {
    new Chart(salesCanvas, {
      type: 'line',
      data: {
        labels: sales.map((point) => point.label),
        datasets: [
          { label: 'E-commerce', data: sales.map((point) => point.ecommerce), borderColor: '#36b7c7', backgroundColor: 'rgba(54,183,199,.10)', pointRadius: 0, pointHoverRadius: 4, borderWidth: 2, tension: .32, fill: true },
          { label: 'Facturación manual', data: sales.map((point) => point.manual), borderColor: '#8499dc', backgroundColor: 'rgba(132,153,220,.06)', pointRadius: 0, pointHoverRadius: 4, borderWidth: 2, tension: .32, fill: false },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: motion,
        interaction: { intersect: false, mode: 'index' },
        plugins: {
          legend: { position: 'bottom', labels: { color: muted, usePointStyle: true, boxWidth: 7, padding: 14, font: { size: 10 } } },
          tooltip: { callbacks: { label: (context) => `${context.dataset.label}: ${currency} ${Number(context.parsed.y).toLocaleString('es-VE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` } },
        },
        scales: {
          x: { grid: { display: false }, border: { display: false }, ticks: { color: muted, maxTicksLimit: 8, maxRotation: 0, font: { size: 9 } } },
          y: { beginAtZero: true, grid: { color: line }, border: { display: false }, ticks: { color: muted, maxTicksLimit: 5, callback: (value) => Number(value).toLocaleString('es-VE', { notation: 'compact', maximumFractionDigits: 1 }), font: { size: 9 } } },
        },
      },
    });
  }

  const productCanvas = document.getElementById('report-products-chart');
  if (productCanvas) {
    new Chart(productCanvas, {
      type: 'bar',
      data: {
        labels: products.map((product) => product.nombre),
        datasets: [{ label: `Venta neta (${currency})`, data: products.map((product) => Number(product.ventas_netas)), backgroundColor: '#43bdc9', borderRadius: 5, maxBarThickness: 20 }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        animation: motion,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (context) => `${currency} ${Number(context.parsed.x).toLocaleString('es-VE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` } },
        },
        scales: {
          x: { beginAtZero: true, grid: { color: line }, border: { display: false }, ticks: { color: muted, callback: (value) => Number(value).toLocaleString('es-VE', { notation: 'compact', maximumFractionDigits: 1 }) } },
          y: { grid: { display: false }, border: { display: false }, ticks: { color: muted, autoSkip: false, font: { size: 9 } } },
        },
      },
    });
  }
});