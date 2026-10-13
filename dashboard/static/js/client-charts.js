(() => {
  if (!window.Chart) return;

  const palette = ['#4bd5ad', '#5aaee0', '#e8ac5d', '#a895f2', '#e47676', '#8ea3b4', '#58c4bd'];
  const currency = new Intl.NumberFormat('es-VE', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  function readSeries(canvas) {
    const source = document.getElementById(canvas.dataset.source);
    if (!source) return [];
    try {
      const series = JSON.parse(source.textContent);
      return Array.isArray(series) ? series : [];
    } catch (error) {
      return [];
    }
  }

  function chartOptions(type, series, isCurrency) {
    const options = {
      responsive: true,
      maintainAspectRatio: false,
      animation: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? false : { duration: 650 },
      plugins: {
        legend: {
          display: type === 'doughnut',
          position: 'bottom',
          labels: {
            color: '#a9bdcc',
            padding: 16,
            usePointStyle: true,
            pointStyle: 'circle',
            font: { family: 'Space Grotesk, sans-serif', size: 11, weight: '600' },
          },
        },
        tooltip: {
          backgroundColor: '#06121e',
          borderColor: '#294358',
          borderWidth: 1,
          titleColor: '#f3f7fa',
          bodyColor: '#d2e0e9',
          padding: 11,
          callbacks: {
            label(context) {
              const label = context.label || context.dataset.label || '';
              const value = Number(
                context.chart.options.indexAxis === 'y'
                  ? context.parsed?.x ?? 0
                  : context.parsed?.y ?? context.parsed ?? 0
              );
              const renderedValue = isCurrency ? `$ ${currency.format(value)}` : value;
              return label ? `${label}: ${renderedValue}` : renderedValue;
            },
          },
        },
      },
    };

    if (type !== 'doughnut') {
      if (canvas.dataset.axis === 'y') {
        options.indexAxis = 'y';
        options.scales = {
          x: {
            beginAtZero: true,
            grid: { color: 'rgba(145, 168, 187, .12)' },
            ticks: { color: '#8299ab', font: { family: 'Space Grotesk, sans-serif', size: 10 } },
            border: { display: false },
          },
          y: {
            grid: { display: false },
            ticks: { color: '#90a6b7', font: { family: 'Space Grotesk, sans-serif', size: 10, weight: '600' } },
            border: { display: false },
          },
        };
      } else {
        options.scales = {
          x: {
            grid: { display: false },
            ticks: { color: '#90a6b7', font: { family: 'Space Grotesk, sans-serif', size: 10, weight: '600' } },
            border: { display: false },
          },
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(145, 168, 187, .12)' },
            ticks: {
              color: '#8299ab',
              font: { family: 'Space Grotesk, sans-serif', size: 10 },
              callback(value) { return isCurrency ? `$ ${currency.format(value)}` : value; },
            },
            border: { display: false },
          },
        };
      }
    } else {
      options.cutout = '68%';
      options.plugins.tooltip.callbacks.label = (context) => `${context.label}: ${context.parsed}`;
    }

    return options;
  }

  document.querySelectorAll('canvas[data-client-chart]').forEach((canvas) => {
    const series = readSeries(canvas);
    if (!series.length) return;

    const type = canvas.dataset.chartType || 'bar';
    const isCurrency = canvas.dataset.currency === 'true';
    const values = series.map((item) => Number(item.value ?? item.total ?? item.count ?? 0));
    if (type === 'doughnut' && values.every((value) => value === 0)) return;

    try {
      new window.Chart(canvas, {
        type,
        data: {
          labels: series.map((item) => item.label),
          datasets: [{
            label: canvas.dataset.label || '',
            data: values,
            borderColor: type === 'doughnut' ? '#0b1927' : '#4bd5ad',
            borderWidth: type === 'doughnut' ? 3 : 2,
            backgroundColor: type === 'doughnut'
              ? palette.slice(0, values.length)
              : type === 'line' ? 'rgba(75, 213, 173, .16)' : 'rgba(75, 213, 173, .78)',
            fill: type === 'line',
            tension: .35,
            pointRadius: type === 'line' ? 3 : 0,
            pointHoverRadius: type === 'line' ? 5 : 0,
            pointBackgroundColor: '#72e2c1',
            borderRadius: type === 'bar' ? 5 : 0,
          }],
        },
        options: chartOptions(type, series, isCurrency),
      });

      canvas.closest('[data-chart-frame]')?.classList.add('is-chart-ready');
    } catch (error) {
      // Mantener visible la alternativa CSS si la librería no puede dibujar.
    }
  });
})();