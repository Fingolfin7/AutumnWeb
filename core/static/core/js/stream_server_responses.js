$(document).ready(function() {
    function connectResponseStream(e) {
        e.preventDefault();

        const formData = new FormData(this);
        const progressBar = document.getElementById('progress-bar');
        const outputText = document.getElementById('output-text');
        const progress = progressBar.querySelector('.progress');

        // Show progress elements
        progressBar.style.display = 'block';
        outputText.style.display = 'block';
        outputText.innerHTML = '';

        // Create EventSource for server-sent events
        const eventSource = new EventSource(`${window.location.pathname}?${new Date().getTime()}`);

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
                }
            }

            // Close connection if import is completed or error occurred
            if (data.message.includes('completed') || data.message.toLowerCase().includes('error')) {
                eventSource.close();
            }
        };

        // Handle errors
        eventSource.onerror = function(error) {
            const logEntry = document.createElement('div');
            logEntry.className = 'log-entry error';
            logEntry.textContent = 'Error: Connection lost. Please try again.';
            outputText.appendChild(logEntry);
            eventSource.close();
        };

        // Send the form data
        fetch(window.location.pathname, {
            method: 'POST',
            body: formData,
            headers: {
                'Accept': 'text/event-stream'
            }
        }).catch(error => {
            const logEntry = document.createElement('div');
            logEntry.className = 'log-entry error';
            logEntry.textContent = 'Error uploading file: ' + error.message;
            outputText.appendChild(logEntry);
            eventSource.close();
        });
    }

    document.getElementById('stream-form').addEventListener('submit', connectResponseStream);
});