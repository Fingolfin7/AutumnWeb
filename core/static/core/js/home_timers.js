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

    function getLocalTimerIds() {
        return $(TIMER_CARD_SELECTOR)
            .map(function() {
                return parseInt($(this).attr('id').replace('timer-', ''), 10);
            })
            .get()
            .filter(Number.isFinite)
            .sort((a, b) => a - b);
    }

    let refreshInFlight = false;

    function refreshTimerSection() {
        if (refreshInFlight) {
            return;
        }
        refreshInFlight = true;

        const refreshUrl = `${window.location.pathname} #active-timers > *`;
        $(ACTIVE_TIMERS_SELECTOR).load(refreshUrl, function() {
            refreshInFlight = false;
            updateDurations();
        });
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
                const serverSet = new Set(serverIds);
                const allLocalTimersStillActive = localIds.every(id => serverSet.has(id));
                const maxVisible = parseInt(timersContainer.data('max-visible'), 10);
                const hasCapacity = Number.isFinite(maxVisible) ? localIds.length < maxVisible : true;
                const canShowNewTimers = hasCapacity && serverIds.length !== localIds.length;

                if (!allLocalTimersStillActive || canShowNewTimers) {
                    refreshTimerSection();
                }
            });
    }

    setInterval(updateDurations, 1000);
    setInterval(syncActiveTimers, SYNC_INTERVAL_MS);

    updateDurations();
    syncActiveTimers();
});
