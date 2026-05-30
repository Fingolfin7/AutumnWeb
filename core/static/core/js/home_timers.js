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

    function getLocalTimerIds() {
        return $(TIMER_CARD_SELECTOR)
            .map(function() {
                return parseInt($(this).attr('id').replace('timer-', ''), 10);
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
            const id = parseInt(timer.attr('id').replace('timer-', ''), 10);

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
                const localStateById = getLocalTimerStateById();
                const serverStateById = getServerTimerStateById(sessions);
                const serverSet = new Set(serverIds);
                const allLocalTimersStillActive = localIds.every(id => serverSet.has(id));
                const maxVisible = parseInt(timersContainer.data('max-visible'), 10);
                const isPartialList = Number.isFinite(maxVisible);

                const hasChanges = isPartialList
                    ? (localIds.length > 0 && !allLocalTimersStillActive)
                    : (
                        hasTimerStateChanges(localStateById, serverStateById) ||
                        !allLocalTimersStillActive ||
                        serverIds.length !== localIds.length
                    );

                if (hasChanges) {
                    refreshTimerSection();
                }
            });
    }

    setInterval(updateDurations, 1000);
    setInterval(syncActiveTimers, SYNC_INTERVAL_MS);

    updateDurations();
    syncActiveTimers();
});
