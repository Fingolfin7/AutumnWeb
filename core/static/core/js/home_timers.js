$(document).ready(function() {
    const ACTIVE_TIMERS_SELECTOR = '#active-timers';
    const TIMER_CARD_SELECTOR = `${ACTIVE_TIMERS_SELECTOR} .card[id^="timer-"]`;
    const SYNC_INTERVAL_MS = 5000;

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
        hours = hours % 24;

        let buildTime = '';
        if (days > 0) {
            buildTime += days + ' day' + (days !== 1 ? 's ' : ' ');
        }
        if (hours > 0) {
            buildTime += hours + ' hour' + (hours !== 1 ? 's ' : ' ');
        }
        if (minutes > 0) {
            buildTime += minutes + ' minute' + (minutes !== 1 ? 's ' : ' ');
        }

        buildTime += seconds + ' second' + (seconds !== 1 ? 's' : '');
        return buildTime;
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

    setInterval(updateDurations, 1000);
    setInterval(refreshTimerSection, SYNC_INTERVAL_MS);

    updateDurations();
});
