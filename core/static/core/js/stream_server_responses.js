$(document).ready(function() {
    function connectResponseStream(e) {
        e.preventDefault();

        const formData = new FormData(this);
        const outputSection = document.getElementById('output-section');
        const progressBar = document.getElementById('progress-bar');
        const outputText = document.getElementById('output-text');
        const progress = progressBar.querySelector('.progress');

        // Show progress elements
        outputSection.style.display = 'block';
        progressBar.style.display = 'block';
        outputText.style.display = 'block';
        outputText.innerHTML = '';

        // set the filename for the title in the output section
        const fileObj = formData.get('file');
        outputSection.querySelector('#output-title').textContent = (fileObj && fileObj.name) ? fileObj.name : '';

        function appendErrorLine(message) {
            const logEntry = document.createElement('div');
            logEntry.className = 'log-entry error';
            logEntry.textContent = message;
            outputText.appendChild(logEntry);
            outputText.scrollTop = outputText.scrollHeight;
        }

        // Send the form data using fetch
        fetch(window.location.pathname, {
            method: 'POST',
            body: formData,  // Send form data, including file to the non-streaming endpoint (for POST request)
        })
        .then(async (response) => {
            if (response.ok) {
                // Once the form is successfully submitted, open the EventSource
                // eventSource is a GET only request, so we need to send the file data in the initial POST request
                const eventSource = new EventSource(window.location.pathname + 'stream');

                // Handle incoming messages
                eventSource.onmessage = function(event) {
                    const data = JSON.parse(event.data);
                    const logEntry = document.createElement('div');
                    logEntry.className = 'log-entry';

                    // Add specific classes based on message content
                    if (data.message.toLowerCase().includes('error')) {
                        logEntry.classList.add('error');
                    } else if (data.message.toLowerCase().includes('success')) {
                        logEntry.classList.add('success');
                    } else if (data.message.toLowerCase().includes('warning')) {
                        logEntry.classList.add('warning');
                    }

                    logEntry.textContent = data.message;
                    outputText.appendChild(logEntry);
                    outputText.scrollTop = outputText.scrollHeight;

                    // Update progress bar if message contains progress info
                    if (data.message.includes('Processing project')) {
                        const match = data.message.match(/Processing project (\d+)\/(\d+)/);
                        if (match) {
                            const [_, current, total] = match;
                            const percentage = (current / total) * 100;
                            progress.style.width = `${percentage}%`;
                            progress.textContent = `${percentage.toFixed(2)}%`;
                        }
                    }

                    // Close connection if import is completed or error occurred
                    if (data.message.includes('completed') || data.message.toLowerCase().includes('error')) {
                        eventSource.close();
                    }
                };

                // Handle errors with the EventSource
                eventSource.onerror = function() {
                    appendErrorLine('Error: Connection lost. Please try again.');
                    eventSource.close();
                };
                return;
            }

            // Non-200: try to show useful validation errors
            let payload = null;
            try {
                payload = await response.json();
            } catch (e) {
                // ignore
            }

            if (payload && payload.errors) {
                appendErrorLine('Error: Please fix the following form issues:');
                Object.keys(payload.errors).forEach((field) => {
                    const msgs = payload.errors[field];
                    (msgs || []).forEach((m) => appendErrorLine(`${field}: ${m}`));
                });
            } else {
                appendErrorLine('Error: Failed to upload form data.');
            }
        })
        .catch(error => {
            appendErrorLine('Error uploading file: ' + error.message);
        });
    }

    document.getElementById('stream-form').addEventListener('submit', connectResponseStream);
});
