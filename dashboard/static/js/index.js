document.addEventListener('DOMContentLoaded', () => {
    const scrollContainer = document.querySelector('.productos-scroll');
    const scrollLeftBtn = document.querySelector('.scroll-btn.left');
    const scrollRightBtn = document.querySelector('.scroll-btn.right');

    if (scrollContainer && scrollLeftBtn && scrollRightBtn) {
        // Calcula el ancho de un producto (incluyendo el gap entre ellos)
        const productWidth = scrollContainer.querySelector('.producto').offsetWidth + 20; // 20px es el gap
        const visibleProducts = 5; // Cantidad de productos visibles
        const scrollAmount = productWidth * visibleProducts; // Desplazamiento basado en productos visibles

        scrollLeftBtn.addEventListener('click', () => {
            scrollContainer.scrollBy({
                left: -scrollAmount,
                behavior: 'smooth',
            });
        });

        scrollRightBtn.addEventListener('click', () => {
            scrollContainer.scrollBy({
                left: scrollAmount,
                behavior: 'smooth',
            });
        });
    }
});