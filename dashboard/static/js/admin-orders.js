document.addEventListener('click', (event) => {
  const button = event.target instanceof Element ? event.target.closest('button[data-confirm]') : null;
  if (button && !window.confirm(button.dataset.confirm)) event.preventDefault();
});

document.addEventListener('DOMContentLoaded', () => {
  const values = document.querySelectorAll('.orders-workspace .metric-value');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  if (!reduceMotion) {
    values.forEach((element, index) => {
      const target = Number(element.textContent.trim());
      if (!Number.isFinite(target)) return;
      const duration = 520;
      const start = performance.now() + index * 55;
      const tick = (now) => {
        const progress = Math.min((now - start) / duration, 1);
        const eased = 1 - ((1 - progress) ** 3);
        element.textContent = Math.round(target * eased).toLocaleString('es-VE');
        if (progress < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }

});