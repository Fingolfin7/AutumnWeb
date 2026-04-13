$(document).ready(function() {
    const ACTIVE_TIMERS_SELECTOR = '#active-timers';
    const TIMER_CARD_SELECTOR = `${ACTIVE_TIMERS_SELECTOR} .card[id^="timer-"]`;

    function updateDurations() {
        $(TIMER_CARD_SELECTOR).each(function() {
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

    function getLocalTimerIds() {
        return $(TIMER_CARD_SELECTOR)
            .map(function() {
                return parseInt($(this).attr('id').replace('timer-', ''), 10);
            })
            .get()
            .filter(Number.isFinite)
            .sort((a, b) => a - b);
    }

    function syncActiveTimers() {
        const timersContainer = $(ACTIVE_TIMERS_SELECTOR);
        if (timersContainer.length === 0) {
            return;
        }

        $.getJSON('/api/list_active_sessions/')
            .done(function(sessions) {
                const serverIds = sessions
                    .filter(session => session.is_active)
                    .map(session => session.id)
                    .sort((a, b) => a - b);
                const localIds = getLocalTimerIds();
                const hasChanges = serverIds.length !== localIds.length || serverIds.some((id, idx) => id !== localIds[idx]);

                if (hasChanges) {
                    window.location.reload();
                }
            });
    }

    // Update durations every second
    setInterval(updateDurations, 1000);
    // Poll server state so timers stopped/started outside the web UI show up quickly.
    setInterval(syncActiveTimers, 5000);

    // Initial update
    updateDurations();
    syncActiveTimers();
});
