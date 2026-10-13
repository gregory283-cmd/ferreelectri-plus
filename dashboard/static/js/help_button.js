(function(){
    // help_button.js - inyecta botón flotante y modal de ayuda global
    function createHelpUI() {
        if (document.getElementById('help-floating-btn')) return; // idempotente

        const style = document.createElement('style');
        style.innerHTML = `
        #help-floating-btn{position:static;right:auto;bottom:auto;z-index:auto;min-height:40px;width:100%;padding:8px 10px;border:1px solid rgba(255,255,255,0.1);border-radius:10px;background:rgba(255,255,255,0.055);color:rgba(255,255,255,0.92);box-shadow:none;font:inherit;font-size:.86rem;font-weight:700;justify-content:flex-start}
        #help-floating-btn.help-fallback{position:fixed;right:24px;bottom:24px;z-index:16000;width:auto;min-height:44px;padding:12px 16px;border:0;border-radius:999px;background:linear-gradient(90deg,#00b2ff 0%,#1976d2 100%);color:#fff;box-shadow:0 8px 30px rgba(3,115,178,0.25)}
        #help-floating-btn .hb-icon{font-size:18px}
        #help-help-modal{position:fixed;right:18px;top:50%;bottom:auto;max-width:520px;width:clamp(300px,44vw,520px);background:#fff;border-radius:14px;box-shadow:-12px 0 36px rgba(2,24,39,0.08), 0 20px 60px rgba(2,24,39,0.28);z-index:16001;padding:18px;display:none;font-family:Inter, Arial, sans-serif;max-height:90vh;overflow:hidden;transform:translateY(-50%)}
        #help-help-modal h3{margin:0 0 8px 0;color:#0a2b3a}
        #help-help-modal p{margin:6px 0;color:#234;line-height:1.35}
        #help-help-modal .help-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}
        #help-help-modal .help-steps{display:flex;flex-direction:column;gap:8px;max-height:62vh;overflow:hidden;padding-right:8px}
        /* Contenedor interior que recibe HTML inyectado y realiza scroll interno */
        #help-help-modal .help-inner{overflow:auto;max-height:calc(62vh - 56px);box-sizing:border-box;padding-right:6px;word-wrap:break-word;white-space:normal}
        #help-help-modal .help-close{background:#e9f5ff;border:1px solid #cfeeff;color:#0a2b3a;padding:8px 10px;border-radius:10px;cursor:pointer}
        #help-help-modal .help-doc{background:linear-gradient(90deg,#00b2ff 0%,#43e97b 100%);color:#fff;padding:8px 10px;border-radius:10px;border:none;cursor:pointer}
        :root[data-theme="dark"] #help-help-modal{background:rgba(8,14,28,0.96);border:1px solid rgba(255,255,255,0.14);box-shadow:-12px 0 36px rgba(0,0,0,0.30), 0 20px 70px rgba(0,0,0,0.42);color:#f8fbff}
        :root[data-theme="dark"] #help-help-modal h3{color:#f8fbff}
        :root[data-theme="dark"] #help-help-modal p{color:rgba(255,255,255,0.92)}
        :root[data-theme="dark"] #help-help-modal .help-inner,
        :root[data-theme="dark"] #help-help-modal .help-inner *{color:rgba(255,255,255,0.94) !important}
        :root[data-theme="dark"] #help-help-modal .help-inner{background:transparent}
        :root[data-theme="dark"] #help-help-modal .help-inner code{color:#d3e7ff;background:rgba(255,255,255,0.06);padding:2px 4px;border-radius:6px}
        :root[data-theme="dark"] #help-help-modal .help-close{background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.16);color:#f8fbff}
        :root[data-theme="dark"] #help-help-modal .help-doc{box-shadow:0 8px 24px rgba(0,0,0,0.18)}
        @media(max-width:700px){#help-help-modal{left:12px;right:12px;top:50%;bottom:auto;width:auto;max-width:unset;max-height:82vh}}
        `;
        document.head.appendChild(style);

        const btn = document.createElement('button');
        btn.id = 'help-floating-btn';
        btn.innerHTML = '<span class="material-symbols-outlined hb-icon" aria-hidden="true">help</span><span class="hb-text">Ayuda</span>';
        btn.title = 'Ayuda de esta página';
        btn.classList.add('utility-help-btn');
        const utilityPanel = document.getElementById('admin-utility-panel');
        if (utilityPanel) {
            utilityPanel.appendChild(btn);
        } else {
            btn.classList.add('help-fallback');
            document.body.appendChild(btn);
        }

        const modal = document.createElement('div');
        modal.id = 'help-help-modal';
        modal.innerHTML = `
            <div class="help-steps" id="help-steps">
                <h3 id="help-title">Ayuda rápida</h3>
                <div class="help-inner"><div id="help-body"><p>Si no se muestra contenido específico, presiona el botón de ayuda para ver pasos generales.</p></div></div>
            </div>
            <div class="help-actions">
                <button class="help-close" id="help-close">Cerrar</button>
            </div>
        `;
        document.body.appendChild(modal);

        function openModal(){
            const utilityDock = document.querySelector('.admin-utility-dock');
            if (utilityDock) utilityDock.classList.add('is-help-open');
            const contentNode = document.getElementById('help-content-template');

            // Solo usamos el contenido real que haya declarado la página con {% block help_content %}
            let html = '';
            if (contentNode) {
                const significant = Array.from(contentNode.childNodes).find(n => {
                    if (n.nodeType === Node.TEXT_NODE) return n.textContent.trim().length > 0;
                    return n.nodeType === Node.ELEMENT_NODE;
                });

                if (significant) {
                    // Si es texto, lo convertimos a párrafo(s); si es elemento, usamos su outerHTML/innerHTML
                    if (significant.nodeType === Node.TEXT_NODE) {
                        html = '<p>' + significant.textContent.trim() + '</p>';
                    } else if (significant.nodeType === Node.ELEMENT_NODE) {
                        html = significant.outerHTML || contentNode.innerHTML;
                    } else {
                        html = contentNode.innerHTML.trim();
                    }
                }
            }

            if (!html) {
                html = '<p>Esta página muestra información y accesos rápidos. Puedes personalizar la ayuda editando el bloque <code>{% block help_content %}</code> en la plantilla.</p>';
            }

            const inner = document.querySelector('#help-steps .help-inner');
            // Always inject content inside the inner scroller to avoid layout overflow
            if (inner) {
                inner.innerHTML = '<div class="help-content">' + html + '</div>';
            } else {
                const body = document.getElementById('help-body');
                if (body) body.innerHTML = html;
            }

            modal.style.display = 'block';
            // small animation
            modal.animate(
                [{transform:'translateY(8px)', opacity:0},{transform:'translateY(0)', opacity:1}],
                {duration:220,easing:'cubic-bezier(.2,.9,.2,1)'}
            );
        }
        function closeModal(){
            modal.style.display = 'none';
            const utilityDock = document.querySelector('.admin-utility-dock');
            if (utilityDock) utilityDock.classList.remove('is-help-open');
        }

        btn.addEventListener('click', function(){
            if (modal.style.display === 'block') closeModal(); else openModal();
        });
        document.getElementById('help-close').addEventListener('click', closeModal);

        // Cerrar al presionar ESC
        document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closeModal(); });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', createHelpUI); else createHelpUI();
})();
