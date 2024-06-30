$(document).ready(function() {

    function updateDurations() {
        $('.card').each(function() {
            let startTime = new Date($(this).data('start-time'));
            let now = new Date();
            let elapsedTime = now - startTime;
            let formattedDuration = formatTime(elapsedTime);

            $(this).find('.timer-duration').text(formattedDuration);
        });
    }

    function formatTime(milliseconds) {
        var seconds = Math.floor(milliseconds / 1000);
        var minutes = Math.floor(seconds / 60);
        var hours = Math.floor(minutes / 60);
        var days = Math.floor(hours / 24);

        if (days > 0) {
            return days + ' day' + (days !== 1 ? 's' : '') + ' ' + (hours % 24) + ' hour' + (hours % 24 !== 1 ? 's' : '');
        } else if (hours > 0) {
            return hours + ' hour' + (hours !== 1 ? 's' : '') + ' ' + (minutes % 60) + ' minute' + (minutes % 60 !== 1 ? 's' : '');
        } else if (minutes > 0) {
            return minutes + ' minute' + (minutes !== 1 ? 's' : '') + ' ' + (seconds % 60) + ' second' + (seconds % 60 !== 1 ? 's' : '');
        } else {
            return seconds + ' second' + (seconds !== 1 ? 's' : '');
        }
    }

    // Update durations every second
    setInterval(updateDurations, 1000);

    // Initial update
    updateDurations();
});
