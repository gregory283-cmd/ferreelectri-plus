// Cliente-side table pagination reutilizable
// Uso: initTablePagination(tbodySelector, paginationContainerSelector, pageSize, optionalSearchInputSelector)
function initTablePagination(tbodySelector, paginationSelector, pageSize, searchSelector) {
    const tbody = document.querySelector(tbodySelector);
    const paginationContainer = document.querySelector(paginationSelector);
    if (!tbody || !paginationContainer) return null;

    const allRows = Array.from(tbody.querySelectorAll('tr'));
    // identificar fila vacía (si existe) - la que contiene un td con colspan
    const emptyRow = allRows.find(r => r.querySelector('td[colspan]')) || null;
    // filas de datos (excluir la fila vacía)
    const dataRows = allRows.filter(r => !r.querySelector('td[colspan]'));

    let currentPage = 1;

    function getVisibleRowsAfterSearch() {
        return dataRows.filter(r => {
            // si está oculto por CSS (buscador), lo consideramos no visible
            const style = window.getComputedStyle(r);
            return style.display !== 'none';
        });
    }

    function renderPageButtons(totalPages) {
        paginationContainer.innerHTML = '';
        if (totalPages <= 1) return;

        const prev = document.createElement('button');
        prev.className = 'pag-btn pag-prev';
        prev.textContent = '« Anterior';
        prev.disabled = currentPage === 1;
        prev.addEventListener('click', () => { currentPage = Math.max(1, currentPage - 1); update(); });
        paginationContainer.appendChild(prev);

        // mostrar botones de páginas (si son muchas, limitar a ventana)
        const maxButtons = 7;
        let start = Math.max(1, currentPage - Math.floor(maxButtons/2));
        let end = Math.min(totalPages, start + maxButtons - 1);
        if (end - start + 1 < maxButtons) {
            start = Math.max(1, end - maxButtons + 1);
        }

        for (let i = start; i <= end; i++) {
            const btn = document.createElement('button');
            btn.className = 'pag-btn pag-page';
            if (i === currentPage) btn.classList.add('active');
            btn.textContent = i;
            btn.addEventListener('click', () => { currentPage = i; update(); });
            paginationContainer.appendChild(btn);
        }

        const next = document.createElement('button');
        next.className = 'pag-btn pag-next';
        next.textContent = 'Siguiente »';
        next.disabled = currentPage === totalPages;
        next.addEventListener('click', () => { currentPage = Math.min(totalPages, currentPage + 1); update(); });
        paginationContainer.appendChild(next);
    }

    function update() {
        const visibleRows = getVisibleRowsAfterSearch();
        const total = visibleRows.length;
        const totalPages = Math.max(1, Math.ceil(total / pageSize));
        if (currentPage > totalPages) currentPage = totalPages;

        // ocultar todas las filas de datos
        dataRows.forEach(r => r.style.display = 'none');

        // mostrar filas para la página actual (entre los rows visibles por el buscador)
        const startIndex = (currentPage - 1) * pageSize;
        const endIndex = startIndex + pageSize;
        const pageRows = visibleRows.slice(startIndex, endIndex);
        pageRows.forEach(r => r.style.display = '');

        // si no hay resultados visibles, mostrar fila vacía (si existe)
        if (total === 0) {
            if (emptyRow) emptyRow.style.display = '';
        } else {
            if (emptyRow) emptyRow.style.display = 'none';
        }

        // renderizar botones
        renderPageButtons(totalPages);
    }

    // si hay input de búsqueda, actualizar paginación al escribir
    if (searchSelector) {
        const input = document.querySelector(searchSelector);
        if (input) {
            input.addEventListener('input', function() {
                // small timeout to let any other search handlers run
                setTimeout(() => { currentPage = 1; update(); }, 50);
            });
        }
    }

    // Exponer método para forzar recálculo externo
    const api = {
        update: update,
        goToPage: function(p) { currentPage = p; update(); }
    };

    // iniciar
    update();
    return api;
}

// Estilos mínimos por JS (si no hay CSS global)
(function insertPaginationStyles(){
    if (document.getElementById('table-pagination-styles')) return;
    const style = document.createElement('style');
    style.id = 'table-pagination-styles';
    style.textContent = `
    .table-pagination { display:flex; gap:8px; align-items:center; justify-content:flex-end; margin-top:12px; }
    .table-pagination .pag-btn { background:#f1f5f9; border:1px solid #dbeaf6; padding:6px 10px; border-radius:6px; cursor:pointer; font-weight:600; color:#1976d2; }
    .table-pagination .pag-btn:disabled { opacity:0.45; cursor:not-allowed; }
    .table-pagination .pag-btn.active { background:#1976d2; color:#fff; }
    `;
    document.head.appendChild(style);
})();

if (typeof module !== 'undefined') module.exports = { initTablePagination };
