(function () {
    function parseSseEvent(rawEvent) {
        const event = { type: 'message', data: '' };
        rawEvent.split(/\r?\n/).forEach((line) => {
            if (line.startsWith('event:')) {
                event.type = line.slice(6).trim();
            } else if (line.startsWith('data:')) {
                event.data += line.slice(5).trimStart();
            }
        });
        if (!event.data) {
            return null;
        }
        try {
            event.payload = JSON.parse(event.data);
        } catch (error) {
            event.payload = { message: event.data };
        }
        return event;
    }

    function scrollToBottom(container) {
        container.scrollTop = container.scrollHeight;
    }

    function removeEmptyState(container) {
        container.querySelectorAll('.empty-state-container').forEach((node) => {
            node.remove();
        });
    }

    function appendMessage(container, className, content) {
        const message = document.createElement('div');
        message.className = className;

        if (className.indexOf('user-message') !== -1) {
            message.dataset.copyText = content;
            const copyButton = document.createElement('button');
            copyButton.type = 'button';
            copyButton.className = 'copy-btn';
            copyButton.title = 'Copy message';
            copyButton.innerHTML = '<i class="fa fa-copy"></i>';
            copyButton.addEventListener('click', function () {
                copyToClipboard(message.dataset.copyText || '', this);
            });
            message.appendChild(copyButton);
        }

        const contentNode = document.createElement('div');
        contentNode.className = 'message-content';
        contentNode.textContent = content;
        message.appendChild(contentNode);

        container.appendChild(message);
        scrollToBottom(container);
        return message;
    }

    function appendAssistantMessage(container, model) {
        const message = document.createElement('div');
        message.className = 'assistant-message streaming';
        message.dataset.model = model || '';

        const copyButton = document.createElement('button');
        copyButton.type = 'button';
        copyButton.className = 'copy-btn';
        copyButton.title = 'Copy message';
        copyButton.innerHTML = '<i class="fa fa-copy"></i>';
        copyButton.addEventListener('click', function () {
            copyToClipboard(message.dataset.copyText || '', this);
        });

        const contentNode = document.createElement('div');
        contentNode.className = 'message-content';

        message.appendChild(copyButton);
        message.appendChild(contentNode);
        container.appendChild(message);
        scrollToBottom(container);
        return message;
    }

    function appendSources(message, sources) {
        if (!sources || !sources.length) {
            return;
        }

        const separator = document.createElement('div');
        separator.className = 'assistant-sources-block';
        separator.innerHTML = '<br><hr><br>';

        const sourcesNode = document.createElement('small');
        sourcesNode.className = 'assistant-sources';
        const strong = document.createElement('strong');
        strong.textContent = 'Sources:';
        sourcesNode.appendChild(strong);
        sourcesNode.appendChild(document.createTextNode(' '));

        sources.forEach((source, index) => {
            const link = document.createElement('a');
            link.href = source.link;
            link.className = 'plain-link';
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = source.title || String(index + 1);
            sourcesNode.appendChild(link);
            if (index < sources.length - 1) {
                sourcesNode.appendChild(document.createTextNode(', '));
            }
        });

        separator.appendChild(sourcesNode);
        message.appendChild(separator);
    }

    function setFormBusy(form, busy) {
        const submitButton = form.querySelector('button[type="submit"]');
        const prompt = form.querySelector('#prompt');
        if (submitButton) {
            submitButton.disabled = busy;
            submitButton.classList.toggle('loading', busy);
        }
        if (prompt) {
            prompt.readOnly = busy;
        }
    }

    function updateTokenUsage(usage) {
        const el = document.getElementById('token-usage');
        if (!el) {
            return;
        }

        const currentPrompt = Number(el.dataset.prompt);
        const currentResponse = Number(el.dataset.response);
        const promptDelta = Number(usage.prompt);
        const responseDelta = Number(usage.response);

        const prompt = (Number.isNaN(currentPrompt) ? 0 : currentPrompt)
            + (Number.isNaN(promptDelta) ? 0 : promptDelta);
        const response = (Number.isNaN(currentResponse) ? 0 : currentResponse)
            + (Number.isNaN(responseDelta) ? 0 : responseDelta);

        el.dataset.prompt = prompt;
        el.dataset.response = response;
        el.textContent = 'In: ' + prompt.toLocaleString() + ' · Out: ' + response.toLocaleString();
    }

    function upsertActiveChatItem(payload) {
        if (!payload.chat_title || !payload.chat_url) {
            return;
        }

        const chatList = document.querySelector('.chat-list');
        if (!chatList) {
            return;
        }

        const chatPath = new URL(payload.chat_url, window.location.origin).pathname;
        let link = Array.from(chatList.querySelectorAll('.chat-item')).find((item) => {
            return new URL(item.href, window.location.origin).pathname === chatPath;
        });

        chatList.querySelectorAll('.chat-item-container, .chat-item').forEach((node) => {
            node.classList.remove('active');
        });

        if (!link) {
            chatList.querySelectorAll('.text-muted').forEach((node) => node.remove());

            const container = document.createElement('div');
            container.className = 'chat-item-container active';

            link = document.createElement('a');
            link.href = payload.chat_url;
            link.className = 'chat-item active';

            const title = document.createElement('span');
            title.className = 'chat-title';
            link.appendChild(title);

            const deleteUrl = new URL(payload.chat_url, window.location.origin);
            deleteUrl.pathname = deleteUrl.pathname.replace(/[^/]+\/$/, `delete/${payload.chat_id}/`);

            const deleteLink = document.createElement('a');
            deleteLink.href = deleteUrl.pathname;
            deleteLink.className = 'delete-chat-btn';
            deleteLink.onclick = function () {
                return confirm('Delete this chat?');
            };
            deleteLink.innerHTML = '<i class="fa fa-trash"></i>';

            container.appendChild(link);
            container.appendChild(deleteLink);
            chatList.prepend(container);
        } else {
            link.classList.add('active');
            if (link.parentElement) {
                link.parentElement.classList.add('active');
            }
        }

        const titleNode = link.querySelector('.chat-title');
        if (titleNode) {
            titleNode.textContent = payload.chat_title;
            titleNode.title = payload.chat_title;
        }
    }

    async function submitStreamingChat(event) {
        event.preventDefault();

        const form = event.currentTarget;
        const prompt = form.querySelector('#prompt');
        const promptText = prompt ? prompt.value.trim() : '';
        if (!promptText) {
            return;
        }

        const container = document.getElementById('conversation-container');
        if (!container) {
            form.submit();
            return;
        }

        removeEmptyState(container);
        appendMessage(container, 'user-message', promptText);
        const assistantMessage = appendAssistantMessage(
            container,
            (form.querySelector('#model') || {}).value
        );
        const assistantContent = assistantMessage.querySelector('.message-content');
        let fullText = '';

        const formData = new FormData(form);
        const streamUrl = new URL(form.dataset.streamUrl, window.location.origin);
        streamUrl.search = window.location.search;

        setFormBusy(form, true);
        if (prompt) {
            prompt.value = '';
        }

        try {
            const response = await fetch(streamUrl.toString(), {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'fetch' },
                credentials: 'same-origin',
            });

            if (!response.ok || !response.body) {
                throw new Error(`Stream failed with status ${response.status}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let done = false;

            while (!done) {
                const read = await reader.read();
                done = read.done;
                buffer += decoder.decode(read.value || new Uint8Array(), {
                    stream: !done,
                });

                const events = buffer.split(/\r?\n\r?\n/);
                buffer = events.pop() || '';

                events.forEach((rawEvent) => {
                    const parsed = parseSseEvent(rawEvent);
                    if (!parsed) {
                        return;
                    }

                    if (parsed.type === 'chat') {
                        if (parsed.payload.chat_url) {
                            window.history.replaceState({}, '', parsed.payload.chat_url);
                        }
                        if (parsed.payload.stream_url) {
                            form.dataset.streamUrl = parsed.payload.stream_url;
                        }
                        return;
                    }

                    if (parsed.type === 'delta') {
                        fullText += parsed.payload.content || '';
                        assistantContent.textContent = fullText;
                        assistantMessage.dataset.copyText = fullText;
                        scrollToBottom(container);
                        return;
                    }

                    if (parsed.type === 'done') {
                        fullText = parsed.payload.content || fullText;
                        if (parsed.payload.html) {
                            assistantContent.innerHTML = parsed.payload.html;
                        } else {
                            assistantContent.textContent = fullText;
                        }
                        assistantMessage.dataset.copyText = fullText;
                        assistantMessage.classList.remove('streaming');
                        if (parsed.payload.model) {
                            assistantMessage.dataset.model = parsed.payload.model;
                        }
                        appendSources(assistantMessage, parsed.payload.sources || []);
                        if (parsed.payload.stream_url) {
                            form.dataset.streamUrl = parsed.payload.stream_url;
                        }
                        upsertActiveChatItem(parsed.payload);
                        updateTokenUsage(parsed.payload.usage || {});
                        scrollToBottom(container);
                        return;
                    }

                    if (parsed.type === 'error') {
                        const message = parsed.payload.message || 'Streaming failed.';
                        fullText += fullText ? `\n\n${message}` : message;
                        assistantContent.textContent = fullText;
                        assistantMessage.dataset.copyText = fullText;
                        assistantMessage.classList.add('stream-error');
                    }
                });
            }
        } catch (error) {
            const message = `Error: ${error.message}`;
            fullText += fullText ? `\n\n${message}` : message;
            assistantContent.textContent = fullText;
            assistantMessage.dataset.copyText = fullText;
            assistantMessage.classList.add('stream-error');
        } finally {
            assistantMessage.classList.remove('streaming');
            setFormBusy(form, false);
            if (prompt) {
                prompt.focus();
            }
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        updateTokenUsage({});

        const form = document.getElementById('chat-form');
        if (form) {
            form.addEventListener('submit', submitStreamingChat);
        }
    });
})();
