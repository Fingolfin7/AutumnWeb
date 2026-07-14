$(document).ready(function() {
    const ACTIVE_TIMERS_SELECTOR = '#active-timers';
    const TIMER_CARD_SELECTOR = `${ACTIVE_TIMERS_SELECTOR} [data-timer-id]`;
    const SYNC_INTERVAL_MS = 30000;

    function updateDurations() {
        $(TIMER_CARD_SELECTOR).each(function() {
            let startTime = new Date($(this).data('start-time'));
            let now = new Date();
            let elapsedTime = now - startTime;
            let formattedDuration = formatTime(elapsedTime);

            $(this).find('.timer-duration').text(formattedDuration);
        });

        $('.timer-stop-after-remaining').each(function() {
            let stopAt = new Date($(this).data('auto-stop-at'));
            let remainingTime = stopAt - new Date();

            $(this).text(formatTime(Math.max(0, remainingTime)));
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

    let refreshInFlight = false;

    function refreshTimerSection() {
        const timersContainer = $(ACTIVE_TIMERS_SELECTOR);
        const refreshUrl = timersContainer.data('refresh-url');
        const surface = timersContainer.data('timer-surface');

        if (refreshInFlight) {
            return;
        }

        if (timersContainer.length === 0 || !refreshUrl || !surface) {
            return;
        }

        refreshInFlight = true;
        $.get(refreshUrl, { surface: surface })
            .done(function(html) {
                timersContainer.replaceWith(html);
                updateDurations();
            })
            .always(function() {
                refreshInFlight = false;
            });
    }

    // Update durations every second
    setInterval(updateDurations, 1000);
    // Refresh the active-timer fragment so external timer changes show up quickly.
    setInterval(refreshTimerSection, SYNC_INTERVAL_MS);

    // Initial update
    updateDurations();
});
