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
        let totalSeconds = Math.floor(milliseconds / 1000);
        let hours = Math.floor(totalSeconds / 3600);
        let remainingSecondsAfterHours = totalSeconds % 3600;
        let minutes = Math.floor(remainingSecondsAfterHours / 60);
        let seconds = remainingSecondsAfterHours % 60;
        let days = Math.floor(hours / 24);
        hours = hours % 24; // Remaining hours after days

        let build_time = '';


        if (days > 0) {
             build_time += days + ' day' + (days !== 1 ? 's ' : ' ');
        }
        if (hours > 0) {
           build_time += hours + ' hour' + (hours !== 1 ? 's ' : ' ');
        }
        if (minutes > 0) {
            build_time += minutes + ' minute' + (minutes !== 1 ? 's ' : ' ') ;
        }

        build_time += seconds + ' second' + (seconds !== 1 ? 's' : '');

        return build_time;
    }

    // Update durations every second
    setInterval(updateDurations, 1000);

    // Initial update
    updateDurations();
});
