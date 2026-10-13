(function () {
  if (window.__ferrebotInitialized) return;
  window.__ferrebotInitialized = true;

  function getCookie(name) {
    var match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return match ? decodeURIComponent(match[1]) : '';
  }

  function typeWriter(text, element) {
    element.textContent = '';
    var index = 0;
    function writeNext() {
      if (index < text.length) {
        element.textContent += text.charAt(index++);
        window.setTimeout(writeNext, 30);
      }
    }
    writeNext();
  }

  document.addEventListener('DOMContentLoaded', function () {
    var fab = document.getElementById('aiAssistantFab');
    var fabContainer = document.getElementById('aiAssistantFabContainer');
    var drawer = document.getElementById('aiAssistantDrawer');
    var overlay = document.getElementById('aiAssistantOverlay');
    var closeButton = document.getElementById('aiAssistantClose');
    var historyToggle = document.getElementById('chat-history-toggle');
    var historyView = document.getElementById('chat-history-view');
    var activeView = document.getElementById('chat-active-view');
    var intro = document.getElementById('aiAssistantIntro');
    var chat = document.getElementById('aiAssistantChat');
    var footer = document.getElementById('aiAssistantFooter');
    var newConversation = document.getElementById('aiAssistantNewConversation');
    var quickActions = document.querySelectorAll('[data-ai-question]');
    var sessionsList = document.getElementById('aiAssistantSessions');
    var historyBack = document.getElementById('chat-new-from-history');
    var form = document.getElementById('aiAssistantForm');
    var input = document.getElementById('aiAssistantInput');
    var sendButton = form && form.querySelector('button[type="submit"]');
    var messages = document.getElementById('aiAssistantMessages');
    var guide = document.getElementById('ferrebotCornerGuide');
    var guideText = document.getElementById('ferrebotGuideText');
    var guideClose = document.getElementById('ferrebotGuideClose');
    if (!fab || !drawer || !overlay || !closeButton || !form || !input || !sendButton || !messages || !historyToggle || !historyView || !activeView || !sessionsList || !intro || !chat || !footer) return;

    var sessionId = null;
    var sending = false;
    var originalIcon = sendButton.innerHTML;

    function scrollToBottom() {
      var chatContainer = document.getElementById('aiAssistantMessages');
      if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function setOpen(open) {
      if (!open && document.activeElement) document.activeElement.blur();
      drawer.classList.toggle('-translate-x-full', !open);
      drawer.classList.toggle('translate-x-0', open);
      overlay.classList.toggle('hidden', !open);
      drawer.setAttribute('aria-hidden', String(!open));
      fab.setAttribute('aria-expanded', String(open));
      if (fabContainer) fabContainer.classList.toggle('hidden', open);
      if (open) {
        showChat();
        window.setTimeout(scrollToBottom, 100);
      }
    }

    function showChat() {
      intro.classList.add('hidden');
      chat.classList.remove('hidden');
      chat.classList.add('flex');
      footer.classList.remove('hidden');
      input.focus();
    }

    function renderMessage(text, user) {
      var row = document.createElement('div');
      row.className = user ? 'flex justify-end' : 'flex items-start gap-3';
      var bubble = document.createElement('div');
      bubble.className = user ? 'max-w-[82%] rounded-2xl bg-blue-600 px-4 py-3 text-sm text-white' : 'max-w-[82%] rounded-2xl bg-gray-800 px-4 py-3 text-sm text-gray-200';
      bubble.textContent = text;
      row.appendChild(bubble);
      messages.appendChild(row);
      scrollToBottom();
      return row;
    }

    function openSession(session) {
      sessionId = session.id;
      var title = document.getElementById('chat-session-title');
      if (title) title.textContent = session.title || 'Nueva Consulta';
      messages.textContent = '';
      (session.messages || []).forEach(function (saved) { renderMessage(saved.content, saved.role === 'user'); });
      historyView.classList.add('hidden');
      activeView.classList.remove('hidden');
    }

    function loadHistory() {
      sessionsList.textContent = '';
      fetch('/api/ai/history/', {credentials: 'same-origin'})
        .then(function (response) { return response.ok ? response.json() : null; })
        .then(function (data) {
          (data && data.sessions || []).forEach(function (session) {
            var row = document.createElement('div');
            row.className = 'flex items-center gap-2 rounded-xl border border-gray-700 bg-gray-950/40 px-3 py-3';
            var open = document.createElement('button');
            open.type = 'button';
            open.className = 'min-w-0 flex-1 text-left text-sm text-white';
            open.textContent = session.title || 'Nueva Consulta';
            open.addEventListener('click', function () { openSession(session); });
            var remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'shrink-0 rounded-lg p-2 text-gray-500 hover:bg-red-500/15 hover:text-red-400';
            remove.setAttribute('aria-label', 'Eliminar conversación');
            remove.innerHTML = '<svg viewBox="0 0 24 24" class="h-4 w-4" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M4 7h16M10 11v6m4-6v6M9 7V5h6v2m-9 0 1 13h8l1-13"/></svg>';
            remove.addEventListener('click', function () {
              fetch('/api/ai/chat/' + session.id + '/delete/', {method: 'DELETE', credentials: 'same-origin', headers: {'X-CSRFToken': getCookie('csrftoken')}})
                .then(function (response) { if (!response.ok) throw new Error('delete'); row.remove(); if (sessionId === session.id) { sessionId = null; messages.textContent = ''; } })
                .catch(function () { remove.classList.add('text-red-500'); });
            });
            row.appendChild(open); row.appendChild(remove); sessionsList.appendChild(row);
          });
          if (!sessionsList.children.length) sessionsList.textContent = 'Aún no tienes conversaciones guardadas.';
        });
      activeView.classList.add('hidden');
      historyView.classList.remove('hidden');
    }

    function showGuide(text) {
      if (!guide || !guideText || !text) return;
      typeWriter(text, guideText);
      guide.setAttribute('aria-hidden', 'false');
      window.requestAnimationFrame(function () {
        guide.classList.remove('translate-y-full', 'opacity-0');
        guide.classList.add('translate-y-0', 'opacity-100', 'animate-bounce');
      });
    }

    var pendingGuide = window.sessionStorage.getItem('ferrebot_guide');
    if (pendingGuide) {
      window.sessionStorage.removeItem('ferrebot_guide');
      showGuide(pendingGuide);
    }

    function handleAction(action) {
      if (!action || !action.type) return;
      if (action.type === 'navigate_url' && String(action.target || '').indexOf('/') === 0) {
        window.sessionStorage.setItem('ferrebot_guide', action.guide_text || '');
        window.location.href = action.target;
        return;
      }
      if (action.type === 'filter_category') {
        window.sessionStorage.setItem('ferrebot_guide', action.guide_text || '');
        window.location.href = '/?categoria=' + encodeURIComponent(action.target || '') + '#productos-grid';
      }
    }

    function sendMessage(text) {
      var message = String(text || '').trim();
      if (!message || sending) return;
      sending = true;
      input.disabled = true;
      sendButton.disabled = true;
      sendButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin" aria-hidden="true"></i>';
      renderMessage(message, true);
      input.value = '';
      var typing = renderMessage('Escribiendo...', false);
      fetch('/api/ai/chat/', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken')}, body: JSON.stringify({message: message, session_id: sessionId})})
        .then(function (response) { return response.json().then(function (data) { if (!response.ok) throw new Error(data.error || 'chat'); return data; }); })
        .then(function (data) { typing.remove(); sessionId = data.session_id || sessionId; renderMessage(data.text || 'No pude responder ahora.', false); handleAction(data.action); })
        .catch(function () { typing.remove(); renderMessage('No pude conectarme ahora. Inténtalo de nuevo.', false); })
        .finally(function () { sending = false; input.disabled = false; sendButton.disabled = false; sendButton.innerHTML = originalIcon; input.focus(); });
    }

    fetch('/api/ai/history/', {credentials: 'same-origin'})
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        var latest = data && data.sessions && data.sessions[0];
        if (!latest) return;
        sessionId = latest.id;
        messages.textContent = '';
        latest.messages.forEach(function (saved) { renderMessage(saved.content, saved.role === 'user'); });
      })
      .catch(function () {});

    fab.addEventListener('click', function () { setOpen(true); });
    closeButton.addEventListener('click', function () { setOpen(false); });
    overlay.addEventListener('click', function () { setOpen(false); });
    historyToggle.addEventListener('click', loadHistory);
    if (historyBack) historyBack.addEventListener('click', function () { historyView.classList.add('hidden'); activeView.classList.remove('hidden'); });
    form.addEventListener('submit', function (event) { event.preventDefault(); sendMessage(input.value); });
    input.addEventListener('keydown', function (event) { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); if (!sending) form.requestSubmit(); } });
    if (guideClose) guideClose.addEventListener('click', function () { guide.classList.add('translate-y-full', 'opacity-0'); guide.classList.remove('animate-bounce'); guide.setAttribute('aria-hidden', 'true'); });
    if (newConversation) newConversation.addEventListener('click', function () { sessionId = null; messages.textContent = ''; showChat(); });
    quickActions.forEach(function (button) { button.addEventListener('click', function () { showChat(); sendMessage(button.getAttribute('data-ai-question')); }); });
  });
}());
