(function () {
  const parseData = (id) => {
    const node = document.getElementById(id);
    if (!node) return [];
    try {
      return JSON.parse(node.textContent || '[]');
    } catch (error) {
      return [];
    }
  };

  document.addEventListener('DOMContentLoaded', function () {
    const root = document.querySelector('.executive-dashboard');
    if (!root) return;
    const currency = root.dataset.currency || '';
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    document.querySelectorAll('.currency-picker select').forEach((select) => {
      select.addEventListener('change', () => select.form.requestSubmit());
    });

    if (!prefersReducedMotion) {
      document.querySelectorAll('.executive-dashboard [data-count]').forEach((element, index) => {
        const target = Number(element.dataset.count);
        if (!Number.isFinite(target)) return;
        const decimals = Number(element.dataset.decimals || 0);
        const formatter = new Intl.NumberFormat('es-VE', {
          minimumFractionDigits: decimals,
          maximumFractionDigits: decimals,
        });
        const prefix = element.dataset.prefix || '';
        const suffix = element.dataset.suffix || '';
        const started = performance.now() + index * 35;
        const duration = 850;
        const tick = (now) => {
          const progress = Math.min(Math.max((now - started) / duration, 0), 1);
          const eased = 1 - ((1 - progress) ** 3);
          element.textContent = `${prefix}${formatter.format(target * eased)}${suffix}`;
          if (progress < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      });
    }

    if (typeof Chart === 'undefined') return;

    const styles = getComputedStyle(root);
    const textColor = styles.getPropertyValue('--dash-muted').trim();
    const lineColor = styles.getPropertyValue('--dash-line').trim();
    const accentColor = styles.getPropertyValue('--dash-cyan').trim();
    const money = (value) => `${currency} ${Number(value || 0).toLocaleString('es-VE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    const sales = parseData('sales-chart-data');
    const audit = parseData('audit-chart-data');

    const salesCanvas = document.getElementById('sales-trend-chart');
    if (salesCanvas) {
      new Chart(salesCanvas, {
        type: 'line',
        data: {
          labels: sales.map((point) => point.label),
          datasets: [{
            label: 'Ventas facturadas',
            data: sales.map((point) => point.total),
            borderColor: accentColor,
            backgroundColor: 'rgba(72, 201, 223, .12)',
            borderWidth: 2.5,
            pointRadius: (context) => context.raw ? 3 : 0,
            pointHoverRadius: 5,
            pointBackgroundColor: accentColor,
            pointBorderColor: styles.getPropertyValue('--dash-surface').trim(),
            pointBorderWidth: 2,
            fill: true,
            tension: .34,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: prefersReducedMotion ? false : { duration: 1350, easing: 'easeOutQuart' },
          animations: { y: { from: 0 } },
          interaction: { intersect: false, mode: 'index' },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: '#0b1725',
              borderColor: 'rgba(148,163,184,.22)',
              borderWidth: 1,
              titleColor: '#edf4fb',
              bodyColor: '#d9e6f2',
              padding: 11,
              displayColors: false,
              callbacks: { label: (context) => money(context.parsed.y) },
            },
          },
          scales: {
            x: {
              grid: { display: false },
              border: { display: false },
              ticks: { color: textColor, maxTicksLimit: 8, maxRotation: 0, font: { size: 10 } },
            },
            y: {
              beginAtZero: true,
              grid: { color: lineColor, drawTicks: false },
              border: { display: false },
              ticks: {
                color: textColor,
                maxTicksLimit: 5,
                padding: 9,
                font: { size: 10 },
                callback: (value) => Number(value).toLocaleString('es-VE', { notation: 'compact', maximumFractionDigits: 1 }),
              },
            },
          },
        },
      });
    }

    const auditCanvas = document.getElementById('audit-activity-chart');
    if (auditCanvas) {
      new Chart(auditCanvas, {
        type: 'bar',
        data: {
          labels: audit.map((point) => point.label),
          datasets: [{
            label: 'Eventos',
            data: audit.map((point) => point.total),
            backgroundColor: audit.map((point) => point.total ? 'rgba(243, 201, 107, .76)' : 'rgba(148,163,184,.14)'),
            hoverBackgroundColor: '#f3c96b',
            borderRadius: 5,
            borderSkipped: false,
            maxBarThickness: 23,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: prefersReducedMotion ? false : { duration: 950, easing: 'easeOutQuart' },
          animations: { y: { from: 0 } },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: '#0b1725',
              borderColor: 'rgba(148,163,184,.22)',
              borderWidth: 1,
              titleColor: '#edf4fb',
              bodyColor: '#d9e6f2',
              padding: 10,
              displayColors: false,
            },
          },
          scales: {
            x: { grid: { display: false }, border: { display: false }, ticks: { color: textColor, font: { size: 10 } } },
            y: { beginAtZero: true, grid: { color: lineColor, drawTicks: false }, border: { display: false }, ticks: { color: textColor, precision: 0, maxTicksLimit: 4, padding: 8, font: { size: 10 } } },
          },
        },
      });
    }
  });
})();
