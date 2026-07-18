(function () {
    'use strict';

    function cookie(name) {
        const match = document.cookie.split(';').map(value => value.trim())
            .find(value => value.startsWith(`${name}=`));
        return match ? decodeURIComponent(match.slice(name.length + 1)) : '';
    }

    function stamp() {
        const now = new Date();
        const pad = value => String(value).padStart(2, '0');
        return `— ${pad(now.getHours())}:${pad(now.getMinutes())} —`;
    }

    function initialise(editor) {
        if (editor.dataset.noteInitialised === 'true') return;
        editor.dataset.noteInitialised = 'true';
        const textarea = editor.querySelector('[data-timer-note-input]');
        const status = editor.querySelector('[data-timer-note-status]');
        const saveButton = editor.querySelector('[data-timer-note-save]');
        const stampButton = editor.querySelector('[data-timer-note-stamp]');
        let timer = null;
        let saving = false;

        function setStatus(message, state) {
            status.textContent = message;
            status.classList.toggle('saved', state === 'saved');
            status.classList.toggle('error', state === 'error');
        }

        function markDirty() {
            editor.dataset.dirty = 'true';
            setStatus('Draft — not saved', 'dirty');
            window.clearTimeout(timer);
            timer = window.setTimeout(save, 1500);
        }

        async function save() {
            if (saving || editor.dataset.dirty !== 'true') return;
            saving = true;
            const sentValue = textarea.value;
            saveButton.disabled = true;
            setStatus('Saving…', 'dirty');
            const body = new URLSearchParams({ note: sentValue });
            try {
                const response = await fetch(editor.dataset.saveUrl, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                        'X-CSRFToken': cookie('csrftoken')
                    },
                    body: body.toString()
                });
                if (!response.ok) throw new Error('save failed');
                if (textarea.value === sentValue) {
                    editor.dataset.dirty = 'false';
                    setStatus(`Saved ✓ ${stamp().replaceAll('—', '').trim()}`, 'saved');
                } else {
                    markDirty();
                }
            } catch (error) {
                editor.dataset.dirty = 'true';
                setStatus('Could not save — try again', 'error');
            } finally {
                saving = false;
                saveButton.disabled = false;
            }
        }

        textarea.addEventListener('input', markDirty);
        saveButton.addEventListener('click', () => {
            window.clearTimeout(timer);
            save();
        });
        stampButton.addEventListener('click', () => {
            const position = textarea.selectionStart;
            const before = textarea.value.slice(0, position);
            const after = textarea.value.slice(position);
            const insertion = `${before && !before.endsWith('\n') ? '\n' : ''}${stamp()} `;
            textarea.value = before + insertion + after;
            const caret = before.length + insertion.length;
            textarea.focus();
            textarea.setSelectionRange(caret, caret);
            markDirty();
        });
    }

    function initialiseAll() {
        document.querySelectorAll('[data-timer-note-editor]').forEach(initialise);
    }

    document.addEventListener('DOMContentLoaded', initialiseAll);
    document.addEventListener('autumn:timers-refreshed', initialiseAll);
})();
