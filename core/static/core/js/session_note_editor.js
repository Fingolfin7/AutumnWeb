(function () {
    function wrapSelection(textarea, before, after) {
        const start = textarea.selectionStart || 0;
        const end = textarea.selectionEnd || 0;
        const selected = textarea.value.slice(start, end);
        const wrapped = `${before}${selected}${after}`;

        textarea.setRangeText(wrapped, start, end, 'end');
        textarea.focus();
    }

    function insertLink(textarea) {
        const start = textarea.selectionStart || 0;
        const end = textarea.selectionEnd || 0;
        const selected = textarea.value.slice(start, end) || 'link text';
        const url = window.prompt('Enter URL', 'https://');

        if (!url) {
            return;
        }

        const markdownLink = `[${selected}](${url})`;
        textarea.setRangeText(markdownLink, start, end, 'end');
        textarea.focus();
    }

    function setupDictation(editorContainer, textarea) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const dictateButton = editorContainer.querySelector('[data-note-action="dictate"]');
        const dictateLabel = dictateButton ? dictateButton.querySelector('[data-dictate-label]') : null;
        const status = editorContainer.querySelector('[data-note-status]');

        if (!dictateButton || !status) {
            return;
        }

        if (!SpeechRecognition) {
            dictateButton.disabled = true;
            if (dictateLabel) {
                dictateLabel.textContent = 'Unavailable';
            }
            status.textContent = 'Dictation unavailable in this browser.';
            return;
        }

        const recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = false;
        recognition.lang = document.documentElement.lang || 'en-US';

        let listening = false;

        dictateButton.addEventListener('click', function () {
            if (listening) {
                recognition.stop();
                return;
            }
            recognition.start();
        });

        recognition.onstart = function () {
            listening = true;
            dictateButton.classList.add('listening');
            if (dictateLabel) {
                dictateLabel.textContent = 'Stop';
            }
            status.textContent = 'Listening...';
        };

        recognition.onend = function () {
            listening = false;
            dictateButton.classList.remove('listening');
            if (dictateLabel) {
                dictateLabel.textContent = 'Dictate';
            }
            status.textContent = 'Dictation stopped.';
        };

        recognition.onerror = function () {
            status.textContent = 'Dictation error. Please try again.';
        };

        recognition.onresult = function (event) {
            const result = event.results[event.results.length - 1];
            if (!result || !result[0]) {
                return;
            }

            const transcript = result[0].transcript.trim();
            if (!transcript) {
                return;
            }

            const prefix = textarea.value.trim().length > 0 ? ' ' : '';
            textarea.value = `${textarea.value}${prefix}${transcript}`;
            status.textContent = 'Added dictated text.';
        };
    }

    function initializeNoteEditor(editorContainer) {
        const textarea = editorContainer.querySelector('textarea');
        if (!textarea) {
            return;
        }

        editorContainer.querySelectorAll('[data-note-action]').forEach(function (button) {
            const action = button.getAttribute('data-note-action');

            if (action === 'dictate') {
                return;
            }

            button.addEventListener('click', function (event) {
                event.preventDefault();

                if (action === 'bold') {
                    wrapSelection(textarea, '**', '**');
                } else if (action === 'italic') {
                    wrapSelection(textarea, '*', '*');
                } else if (action === 'link') {
                    insertLink(textarea);
                }
            });
        });

        setupDictation(editorContainer, textarea);
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-note-editor]').forEach(initializeNoteEditor);
    });
})();
