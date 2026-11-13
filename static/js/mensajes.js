(() => {
    const page = document.getElementById('messages-page');
    if (!page) return;

    const panel = document.querySelector('.conversation-panel[data-conversation-id]');
    const connectionStatus = document.getElementById('connection-status');
    const conversationId = panel ? Number(panel.dataset.conversationId) : null;
    const history = document.getElementById('message-history');
    const form = document.getElementById('message-form');
    const input = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const typingIndicator = document.getElementById('typing-indicator');
    const sendError = document.getElementById('send-error');

    if (typeof io !== 'function') {
        if (connectionStatus) {
            connectionStatus.textContent = 'Sin conexión en tiempo real; los mensajes se enviarán con recarga.';
            connectionStatus.classList.add('text-danger');
        }
        return;
    }

    const socket = io();
    let socketReady = false;
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

    function formatDay(value) {
        return new Intl.DateTimeFormat('es-AR', {
            day: '2-digit',
            month: '2-digit'
        }).format(new Date(value));
    }

    function appendMessage(message) {
        if (!history) return;
        if (history.querySelector(`[data-message-id="${message.id}"]`)) return;
        const emptyHistory = document.getElementById('empty-history');
        if (emptyHistory) emptyHistory.remove();

        const isOwnMessage = message.sender_id === window.yamitasUserId;
        const row = document.createElement('div');
        row.className = `message-row${isOwnMessage ? ' message-row-own' : ''}`;
        row.dataset.messageId = message.id;

        const bubble = document.createElement('div');
        bubble.className = `message-bubble${isOwnMessage ? ' message-bubble-own' : ''}`;

        if (!isOwnMessage) {
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

    function updateConversationList(message) {
        const list = document.querySelector('.conversation-list-items');
        if (!list) return;

        const conversationLink = list.querySelector(
            `[data-conversation-id="${message.conversation_id}"]`
        );
        const contactName = message.buyer_id === window.yamitasUserId
            ? message.seller_name
            : message.buyer_name;
        const link = conversationLink || document.createElement('a');

        if (!conversationLink) {
            const emptyList = document.getElementById('empty-conversations');
            if (emptyList) emptyList.remove();
            link.className = 'conversation-link';
            link.dataset.conversationId = message.conversation_id;
            link.href = `${window.yamitasMessagesUrl}?conversacion=${message.conversation_id}`;

            const heading = document.createElement('div');
            heading.className = 'd-flex justify-content-between gap-2';
            const contact = document.createElement('strong');
            contact.className = 'text-truncate';
            const date = document.createElement('small');
            date.className = 'conversation-date text-muted flex-shrink-0';
            heading.append(contact, date);

            const product = document.createElement('div');
            product.className = 'small text-muted text-truncate';
            const preview = document.createElement('div');
            preview.className = 'conversation-preview small text-muted text-truncate';
            link.append(heading, product, preview);
        }

        link.querySelector('strong').textContent = contactName;
        link.querySelector('.conversation-date').textContent = formatDay(message.created_at);
        link.querySelector('.small.text-muted.text-truncate').textContent = message.product_name;
        link.querySelector('.conversation-preview').textContent = message.content;
        list.prepend(link);
    }

    socket.on('connect', () => {
        socketReady = false;
        if (connectionStatus) {
            connectionStatus.textContent = 'Conectando…';
            connectionStatus.classList.remove('text-danger', 'text-success');
        }
        if (!conversationId) {
            socketReady = true;
            return;
        }
        socket.emit('join_conversation', {
            conversation_id: conversationId,
            csrf_token: window.yamitasCsrfToken
        }, (response) => {
            if (!response || !response.ok) {
                if (connectionStatus) {
                    connectionStatus.textContent = response?.error || 'No se pudo abrir el chat en tiempo real.';
                    connectionStatus.classList.add('text-danger');
                }
                return;
            }
            socketReady = true;
            if (connectionStatus) {
                connectionStatus.textContent = 'En línea';
                connectionStatus.classList.add('text-success');
            }
        });
    });

    socket.on('disconnect', () => {
        socketReady = false;
        if (connectionStatus) {
            connectionStatus.textContent = 'Reconectando…';
            connectionStatus.classList.remove('text-success');
            connectionStatus.classList.add('text-danger');
        }
    });

    socket.on('connect_error', () => {
        socketReady = false;
        if (connectionStatus) {
            connectionStatus.textContent = 'Sin conexión en tiempo real; los mensajes se enviarán con recarga.';
            connectionStatus.classList.remove('text-success');
            connectionStatus.classList.add('text-danger');
        }
    });

    socket.on('new_message', (message) => {
        updateConversationList(message);
        if (conversationId === message.conversation_id) appendMessage(message);
    });

    socket.on('typing', (data) => {
        if (!typingIndicator) return;
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

    if (input) input.addEventListener('input', () => {
        if (!conversationId) return;
        if (!socketReady) return;
        socket.emit('typing', {
            conversation_id: conversationId,
            is_typing: true,
            csrf_token: window.yamitasCsrfToken
        });
        window.clearTimeout(typingTimer);
        typingTimer = window.setTimeout(() => {
            socket.emit('typing', {
                conversation_id: conversationId,
                is_typing: false,
                csrf_token: window.yamitasCsrfToken
            });
        }, 900);
    });

    if (input && form) input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    if (form && input) form.addEventListener('submit', (event) => {
        if (!socketReady) return;
        event.preventDefault();
        const content = input.value.trim();
        if (!content) return;

        sendButton.disabled = true;
        sendError.textContent = '';
        socket.emit('send_message', {
            conversation_id: conversationId,
            content,
            csrf_token: window.yamitasCsrfToken
        }, (response) => {
            sendButton.disabled = false;
            if (!response || !response.ok) {
                sendError.textContent = response?.error || 'No se pudo enviar el mensaje.';
                return;
            }
            input.value = '';
            socket.emit('typing', {
                conversation_id: conversationId,
                is_typing: false,
                csrf_token: window.yamitasCsrfToken
            });
            input.focus();
        });
    });

    window.yamitasUserId = Number(page.dataset.userId);
    if (history) scrollToLatest();
})();
