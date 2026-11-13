(() => {
    const panel = document.querySelector('.conversation-panel[data-conversation-id]');
    if (!panel) return;

    const connectionStatus = document.getElementById('connection-status');
    if (typeof io !== 'function') {
        connectionStatus.textContent = 'No se pudo cargar el chat. Recarga la página para volver a intentar.';
        connectionStatus.classList.add('text-danger');
        return;
    }

    const conversationId = Number(panel.dataset.conversationId);
    const history = document.getElementById('message-history');
    const form = document.getElementById('message-form');
    const input = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const typingIndicator = document.getElementById('typing-indicator');
    const sendError = document.getElementById('send-error');
    const socket = io();
    let typingTimer;
    let remoteTypingTimer;

    function scrollToLatest() {
        history.scrollTop = history.scrollHeight;
    }

    function formatTime(value) {
        return new Intl.DateTimeFormat('es-AR', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        }).format(new Date(value));
    }

    function appendMessage(message) {
        if (history.querySelector(`[data-message-id="${message.id}"]`)) return;
        const emptyHistory = document.getElementById('empty-history');
        if (emptyHistory) emptyHistory.remove();

        const row = document.createElement('div');
        row.className = `message-row${message.sender_id === window.yamitasUserId ? ' message-row-own' : ''}`;
        row.dataset.messageId = message.id;

        const bubble = document.createElement('div');
        bubble.className = `message-bubble${message.sender_id === window.yamitasUserId ? ' message-bubble-own' : ''}`;

        if (message.sender_id !== window.yamitasUserId) {
            const sender = document.createElement('strong');
            sender.className = 'message-sender';
            sender.textContent = message.sender_name;
            bubble.append(sender);
        }

        const content = document.createElement('p');
        content.className = 'message-content mb-1';
        content.textContent = message.content;
        const time = document.createElement('time');
        time.className = 'message-time';
        time.textContent = formatTime(message.created_at);
        bubble.append(content, time);
        row.append(bubble);
        history.append(row);
        scrollToLatest();
    }

    socket.on('connect', () => {
        connectionStatus.textContent = 'En línea';
        connectionStatus.classList.remove('text-danger');
        connectionStatus.classList.add('text-success');
        socket.emit('join_conversation', { conversation_id: conversationId }, (response) => {
            if (!response || !response.ok) {
                connectionStatus.textContent = response?.error || 'No se pudo abrir el chat';
                connectionStatus.classList.remove('text-success');
                connectionStatus.classList.add('text-danger');
            }
        });
    });

    socket.on('disconnect', () => {
        connectionStatus.textContent = 'Reconectando…';
        connectionStatus.classList.remove('text-success');
        connectionStatus.classList.add('text-danger');
    });

    socket.on('connect_error', () => {
        connectionStatus.textContent = 'Sin conexión. Reintentando…';
        connectionStatus.classList.remove('text-success');
        connectionStatus.classList.add('text-danger');
    });

    socket.on('new_message', appendMessage);

    socket.on('typing', (data) => {
        if (data.user_id === window.yamitasUserId || !data.is_typing) {
            typingIndicator.textContent = '';
            return;
        }
        typingIndicator.textContent = `${data.username} está escribiendo…`;
        window.clearTimeout(remoteTypingTimer);
        remoteTypingTimer = window.setTimeout(() => {
            typingIndicator.textContent = '';
        }, 1800);
    });

    input.addEventListener('input', () => {
        socket.emit('typing', { conversation_id: conversationId, is_typing: true });
        window.clearTimeout(typingTimer);
        typingTimer = window.setTimeout(() => {
            socket.emit('typing', { conversation_id: conversationId, is_typing: false });
        }, 900);
    });

    input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        const content = input.value.trim();
        if (!content || !socket.connected) {
            if (!socket.connected) sendError.textContent = 'Esperando conexión para enviar el mensaje…';
            return;
        }

        sendButton.disabled = true;
        sendError.textContent = '';
        socket.emit('send_message', { conversation_id: conversationId, content }, (response) => {
            sendButton.disabled = false;
            if (!response || !response.ok) {
                sendError.textContent = response?.error || 'No se pudo enviar el mensaje.';
                return;
            }
            input.value = '';
            socket.emit('typing', { conversation_id: conversationId, is_typing: false });
            input.focus();
        });
    });

    scrollToLatest();
})();
