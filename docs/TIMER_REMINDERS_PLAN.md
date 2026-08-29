# Timer reminders and browser push

## Product scope

AutumnWeb will support reminders attached to an active timer:

- notify once after an elapsed duration;
- notify once at a specific date and time;
- notify at a fixed interval while the timer remains active;
- notify when a server-side auto-stop completes;
- show and cancel active reminder rules from the timer UI.

Generic standalone reminders are deliberately out of scope. Reminder rules end
when their timer stops or is deleted. Periodic rules skip missed occurrences
instead of producing catch-up bursts.

## Data and delivery design

1. Store each browser push subscription against its authenticated user and
   browser endpoint. A user may have multiple subscriptions, but an endpoint
   is globally unique because one service-worker registration represents one
   physical browser profile. Re-subscribing transfers that endpoint to the
   current authenticated user. Endpoints that return `404` or `410` are
   disabled.
2. Store timer reminder rules separately from delivery events. A rule records
   its session, mode, next scheduled instant, optional interval, message, and
   active state.
3. Use a small transactional outbox for notification events. Claiming a due
   rule advances or completes the rule and creates one uniquely keyed outbox
   event in the same transaction. Network requests happen only after that
   transaction commits.
4. Auto-stop completion writes its own uniquely keyed outbox event from the
   authoritative session-stop path. It is not represented as a user reminder
   rule.
5. Delivery fans an outbox event out to all active subscriptions. Delivery
   attempts are recorded per event and subscription so retries do not resend
   successful device deliveries. Transient failures use bounded exponential
   backoff and end in a terminal failed state; permanent `4xx` failures do not
   retry.
6. A management command dispatches due rules and pending outbox deliveries.
   Each pass first performs a global expired-timer sweep, then claims reminder
   rules, then flushes the outbox. It supports a single pass for cron and a
   bounded polling loop for local or background-worker use. No scheduler
   starts from `AppConfig.ready()`.

## Dispatch runtime

The production baseline is a Render Cron Job running
`python manage.py dispatch_timer_reminders --once` every minute. Version one
therefore accepts approximately one-minute scheduling granularity plus process
startup and push-provider latency. A continuously running Render background
worker may use the bounded loop for tighter delivery later.

The dispatcher is the component that turns existing lazy auto-stop semantics
into near-real-time behavior: it calls `stop_expired_timers()` for all users
before firing ordinary reminders. Web requests may still perform their current
lazy sweep, so repeated and concurrent sweeps must be harmless. Local testing
runs one dispatcher process at a time.

## Browser and configuration work

- Add authenticated, CSRF-protected subscribe, unsubscribe, status, and test
  endpoints.
- Configure VAPID public/private keys and subject through environment settings.
  Do not commit a private key.
- Add `push` and `notificationclick` handlers to the existing service worker.
  Notification clicks open the relevant timer page. Version one does not
  perform state-changing actions directly from a notification. Use stable
  notification tags to collapse browser-level duplicate delivery, focus an
  existing Autumn window before opening a new one, and leave the service-worker
  cache version unchanged because the precache list does not change.
- Ask for browser permission only after the user deliberately chooses to
  enable notifications. Explain when Autumn will notify before opening the
  browser permission prompt.

## Timer UI

The Start Timer page keeps its existing two-decision structure and adds a
compact third, optional section beneath **Stop after**:

- None
- Once after: amount and minutes/hours
- Every: amount and minutes/hours
- At: local date and time, with an explicit preview in the profile timezone

The active timer surface shows the reminder mode and next fire time with a
Cancel action. The backend permits multiple reminder rules per session even if
the first UI creates only one.

## Correctness and security

- Parse user input in the profile timezone and store aware UTC instants.
- Reject ambiguous or nonexistent local wall times at DST transitions instead
  of silently choosing a fold.
- Enforce reminder, session, and subscription ownership on every endpoint.
- Reject reminders for stopped sessions and implausibly short intervals.
- Cancel active rules when the canonical session mutation path transitions
  `end_time` from null to non-null. Restarting the same session does not revive
  cancelled rules.
- Claim due work with portable conditional updates plus unique event keys; do
  not depend on `select_for_update(skip_locked=True)`, which SQLite lacks.
- Floor scheduled instants before building dedupe keys so SQLite and PostgreSQL
  agree.
- Do not hold database locks while calling external push endpoints.
- Treat absent VAPID configuration or push subscriptions as a clear,
  terminal unavailable/no-recipient state; reminder persistence must not
  create an endless retry loop or unbounded outbox growth.
- Never call a push provider from a web request. Enqueue inside the transaction
  and deliver from the dispatcher after commit.
- Truncate notification payloads to remain safely below Web Push payload
  limits.

## Verification

- Model constraints and migrations.
- Ownership, authentication, CSRF, and malformed-subscription tests.
- One-shot, interval, missed-interval, idempotency, retry, and expired-endpoint
  delivery tests.
- Concurrent claim and concurrent auto-stop tests that prove duplicate work is
  harmless on SQLite and PostgreSQL semantics.
- Endpoint ownership-transfer and multi-device partial-failure tests.
- Retry-cap/dead-letter and absent-VAPID/no-recipient terminal-state tests.
- Stop, delete, manual restart, and auto-stop lifecycle tests.
- A restart test proving stopped reminder rules remain cancelled.
- A request-cycle test proving timer expiry and stop perform no network calls.
- Profile-timezone and DST-boundary tests.
- Timer note handoff and optimistic-version regression tests with reminders.
- Service-worker and browser JavaScript syntax checks.
- Existing PWA, timer, API, and full Django suites.
- Localhost walkthrough covering permission, subscription, timer creation,
  reminder display/cancel, notification delivery, auto-stop, and responsive UI.

## Follow-up outside this branch

Expose the same server reminder API to Autumn CLI so reminders created in one
client are visible and cancellable in the other. Do not preserve CLI-specific
PID, polling, or background-process controls in the shared contract.
