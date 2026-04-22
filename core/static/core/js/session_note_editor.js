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

        function resolveRecognitionLanguage() {
            const candidates = [
                textarea.getAttribute('lang'),
                editorContainer.getAttribute('lang'),
                document.documentElement.lang,
                navigator.language,
                navigator.languages && navigator.languages.length ? navigator.languages[0] : null,
            ];

            for (let index = 0; index < candidates.length; index += 1) {
                const candidate = candidates[index];
                if (!candidate) {
                    continue;
                }

                const normalized = String(candidate).trim();
                if (!normalized) {
                    continue;
                }

                if (/^[a-z]{2}$/i.test(normalized)) {
                    if (normalized.toLowerCase() === 'en') {
                        return 'en-US';
                    }
                    return `${normalized.toLowerCase()}-${normalized.toUpperCase()}`;
                }

                return normalized;
            }

            return 'en-US';
        }

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
        recognition.interimResults = true;
        recognition.maxAlternatives = 1;
        recognition.lang = resolveRecognitionLanguage();

        let listening = false;
        let shouldListen = false;
        let restartTimer = null;
        let transcriptAnchorStart = null;
        let transcriptAnchorEnd = null;
        let committedTranscript = '';
        let finalStatusMessage = '';

        function debugLog(message, extra) {
            if (typeof console === 'undefined' || typeof console.debug !== 'function') {
                return;
            }
            if (typeof extra === 'undefined') {
                console.debug('[dictation]', message);
            } else {
                console.debug('[dictation]', message, extra);
            }
        }

        function setIdleState(message) {
            listening = false;
            dictateButton.classList.remove('listening');
            if (dictateLabel) {
                dictateLabel.textContent = 'Dictate';
            }
            status.textContent = finalStatusMessage || message;
        }

        function joinTranscriptParts(left, right) {
            if (!left) {
                return right || '';
            }
            if (!right) {
                return left;
            }
            return `${left} ${right}`.trim();
        }

        function stopDictation(message) {
            shouldListen = false;
            if (restartTimer) {
                window.clearTimeout(restartTimer);
                restartTimer = null;
            }
            if (listening) {
                recognition.stop();
            } else {
                setIdleState(message || 'Dictation stopped.');
            }
        }

        function resetTranscriptSession() {
            transcriptAnchorStart = null;
            transcriptAnchorEnd = null;
            committedTranscript = '';
            finalStatusMessage = '';
        }

        function renderTranscript(interimTranscript) {
            if (transcriptAnchorStart === null || transcriptAnchorEnd === null) {
                transcriptAnchorStart = textarea.selectionStart || textarea.value.length;
                transcriptAnchorEnd = textarea.selectionEnd || transcriptAnchorStart;
            }

            const transcript = joinTranscriptParts(committedTranscript, interimTranscript || '').trim();
            if (!transcript) {
                return;
            }

            const start = transcriptAnchorStart;
            const end = transcriptAnchorEnd;
            const needsLeadingSpace =
                start > 0 &&
                !/\s$/.test(textarea.value.slice(0, start)) &&
                transcript.length > 0;
            const insertion = `${needsLeadingSpace ? ' ' : ''}${transcript}`;

            textarea.setRangeText(insertion, start, end, 'end');
            transcriptAnchorEnd = start + insertion.length;
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
            textarea.focus();
        }

        dictateButton.addEventListener('click', function () {
            if (shouldListen) {
                stopDictation('Dictation stopped.');
                return;
            }
            resetTranscriptSession();
            shouldListen = true;
            debugLog('start requested', { lang: recognition.lang });
            recognition.start();
        });

        recognition.onstart = function () {
            listening = true;
            finalStatusMessage = '';
            dictateButton.classList.add('listening');
            if (dictateLabel) {
                dictateLabel.textContent = 'Stop';
            }
            status.textContent = 'Listening...';
            debugLog('onstart');
        };

        recognition.onend = function () {
            debugLog('onend', { shouldListen: shouldListen, finalStatusMessage: finalStatusMessage });
            if (restartTimer) {
                window.clearTimeout(restartTimer);
                restartTimer = null;
            }

            if (!shouldListen) {
                setIdleState('Dictation stopped.');
                resetTranscriptSession();
                return;
            }

            listening = false;
            status.textContent = 'Still listening...';
            restartTimer = window.setTimeout(function () {
                if (shouldListen && !listening) {
                    debugLog('restart requested');
                    recognition.start();
                }
            }, 150);
        };

        recognition.onaudiostart = function () {
            debugLog('onaudiostart');
            status.textContent = 'Microphone connected. Listening...';
        };

        recognition.onaudioend = function () {
            debugLog('onaudioend');
        };

        recognition.onsoundstart = function () {
            debugLog('onsoundstart');
            status.textContent = 'Sound detected...';
        };

        recognition.onsoundend = function () {
            debugLog('onsoundend');
        };

        recognition.onspeechstart = function () {
            debugLog('onspeechstart');
            status.textContent = 'Speech detected...';
        };

        recognition.onspeechend = function () {
            debugLog('onspeechend');
            status.textContent = 'Speech ended. Processing...';
        };

        recognition.onerror = function (event) {
            const errorCode = event && event.error ? event.error : 'unknown';
            debugLog('onerror', event);

            if (errorCode === 'no-speech') {
                status.textContent = 'No speech detected. Keep talking or try again.';
                return;
            }

            if (errorCode === 'aborted') {
                finalStatusMessage = 'Dictation stopped.';
                setIdleState('Dictation stopped.');
                resetTranscriptSession();
                return;
            }

            if (errorCode === 'not-allowed' || errorCode === 'service-not-allowed') {
                finalStatusMessage = 'Microphone access was blocked. Please allow microphone permissions and try again.';
                stopDictation(finalStatusMessage);
                return;
            }

            finalStatusMessage = `Dictation error (${errorCode}). Please try again.`;
            stopDictation(finalStatusMessage);
        };

        recognition.onresult = function (event) {
            debugLog('onresult', event);
            let finalTranscript = '';
            let interimTranscript = '';

            for (let index = event.resultIndex; index < event.results.length; index += 1) {
                const result = event.results[index];
                if (!result || !result[0]) {
                    continue;
                }

                const chunk = result[0].transcript.trim();
                if (!chunk) {
                    continue;
                }

                if (result.isFinal) {
                    finalTranscript = joinTranscriptParts(finalTranscript, chunk);
                } else {
                    interimTranscript = joinTranscriptParts(interimTranscript, chunk);
                }
            }

            if (finalTranscript) {
                committedTranscript = joinTranscriptParts(committedTranscript, finalTranscript);
            }

            if (!committedTranscript && !interimTranscript) {
                return;
            }

            renderTranscript(interimTranscript);
            status.textContent = shouldListen ? 'Listening...' : 'Added dictated text.';
            debugLog('transcript updated', {
                committedTranscript: committedTranscript,
                interimTranscript: interimTranscript,
            });
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
