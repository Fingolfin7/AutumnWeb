$(document).ready(function() {
    const ACTIVE_TIMERS_SELECTOR = '#active-timers';
    const TIMER_CARD_SELECTOR = `${ACTIVE_TIMERS_SELECTOR} [data-timer-id]`;
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
                return parseInt($(this).data('timer-id'), 10);
            })
            .get()
            .filter(Number.isFinite)
            .sort((a, b) => a - b);
    }

    function timerInstant(value) {
        const timestamp = new Date(value).getTime();
        return Number.isFinite(timestamp) ? timestamp : null;
    }

    function getLocalTimerStateById() {
        const stateById = new Map();

        $(TIMER_CARD_SELECTOR).each(function() {
            const timer = $(this);
            const id = parseInt(timer.data('timer-id'), 10);

            if (Number.isFinite(id)) {
                stateById.set(id, {
                    start: timerInstant(timer.data('start-time')),
                    autoStopAt: timerInstant(timer.data('auto-stop-at')),
                    projectId: parseInt(timer.data('project-id'), 10)
                });
            }
        });

        return stateById;
    }

    function getServerTimerStateById(sessions) {
        const stateById = new Map();

        sessions
            .filter(session => session.is_active)
            .forEach(function(session) {
                stateById.set(session.id, {
                    start: timerInstant(session.start_time),
                    autoStopAt: timerInstant(session.auto_stop_at),
                    projectId: parseInt(session.project_id, 10)
                });
            });

        return stateById;
    }

    function hasTimerStateChanges(localStateById, serverStateById) {
        for (const [id, localState] of localStateById) {
            const serverState = serverStateById.get(id);

            if (
                !serverState ||
                localState.start !== serverState.start ||
                localState.autoStopAt !== serverState.autoStopAt ||
                localState.projectId !== serverState.projectId
            ) {
                return true;
            }
        }

        return false;
    }

    let refreshInFlight = false;

    function refreshTimerSection() {
        if (refreshInFlight) {
            return;
        }
        refreshInFlight = true;

        const refreshUrl = `${window.location.pathname} ${ACTIVE_TIMERS_SELECTOR} > *`;
        $(ACTIVE_TIMERS_SELECTOR).load(refreshUrl, function() {
            refreshInFlight = false;
            updateDurations();
        });
    }

    function syncActiveTimers() {
        const timersContainer = $(ACTIVE_TIMERS_SELECTOR);

        $.getJSON('/api/list_active_sessions/')
            .done(function(sessions) {
                const serverIds = sessions
                    .filter(session => session.is_active)
                    .map(session => session.id)
                    .sort((a, b) => a - b);

                if (timersContainer.length === 0) {
                    return;
                }

                const localIds = getLocalTimerIds();
                const localStateById = getLocalTimerStateById();
                const serverStateById = getServerTimerStateById(sessions);
                const serverSet = new Set(serverIds);
                const allLocalTimersStillActive = localIds.every(id => serverSet.has(id));
                const isPartialList = timersContainer.data('partial-list') === true;

                let hasChanges = false;
                if (isPartialList) {
                    hasChanges = localIds.length > 0 && !allLocalTimersStillActive;
                } else {
                    hasChanges = hasTimerStateChanges(localStateById, serverStateById) ||
                        !allLocalTimersStillActive ||
                        serverIds.length !== localIds.length;
                }

                if (hasChanges) {
                    refreshTimerSection();
                }
            });
    }

    // Update durations every second
    setInterval(updateDurations, 1000);
    // Poll server state so timers stopped/started outside the web UI show up quickly.
    setInterval(syncActiveTimers, SYNC_INTERVAL_MS);

    // Initial update
    updateDurations();
    syncActiveTimers();
});
