# Scheduled reminders, commitment checks, and weekly reviews

## Product contract

This phase builds the three notification categories agreed after timer-bound
reminders:

1. **User-scheduled reminder** — for example, “You planned CMG prep for 18:30.”
   Notification actions open a prefilled Start Timer page or a Snooze page.
2. **Commitment becoming actionable** — for example, “Exercise: 1 session
   remaining; period ends Sunday.” Notification actions open a relevant Start
   Timer page or the commitment detail.
3. **Optional weekly review** — for example, “6h 12m across 4 projects; 2 of 3
   commitments met.” The notification opens a dedicated weekly-review page.

These categories are sparse and intentional. Scheduled reminders are created
explicitly by the user. Commitment checks and weekly reviews are opt-in and
independently configurable. Autumn does not add inactivity guilt, streak-loss
warnings, routine confirmations, or AI-written coaching.

## Reuse and boundaries

- Reuse `NotificationEvent`, `NotificationDelivery`, Web Push subscriptions,
  VAPID validation, and the shared dispatcher/outbox.
- Keep timer-bound `TimerReminder` rules unchanged. Standalone schedules have a
  separate model and lifecycle.
- Reuse commitment scope, period, banking, and progress calculations from
  `core.commitments`; notification code must not reimplement commitment math.
- Reuse completed-session reporting primitives for weekly totals.
- Notification actions navigate to safe same-origin Autumn pages. They do not
  start timers, snooze schedules, or mutate commitments invisibly from the
  service worker.
- CLI exposure remains outside this phase.

## Data model

### NotificationPreference

One row per user, created lazily or by migration defaults:

- `scheduled_reminders_enabled` (default true; explicit schedules still remain
  visible when delivery is paused);
- `commitment_checks_enabled` (default false);
- `weekly_review_enabled` (default false);
- `commitment_check_time` in the profile timezone (default 18:00);
- `weekly_review_weekday` and `weekly_review_time` in the profile timezone
  (default Monday at 09:00);
- `next_commitment_check_at` and `next_weekly_review_at` as indexed aware UTC
  instants used for portable compare-and-set claiming.

Changing the profile timezone or preference schedule recomputes the next UTC
instants. DST gaps and folds are rejected in user-entered schedules; recurring
slots advance in local wall time, not by adding fixed UTC seconds. When a later
recurrence lands in a DST gap it advances to the first valid local minute; when
it lands in a fold it uses the earlier occurrence. The same deterministic rule
applies to the "tomorrow" snooze choice.

Background evaluation must never rely on request middleware. Each user's
commitment checks and reviews run inside `timezone.override(profile_zone)`;
commitment period calculations use the governing revision's frozen timezone.

### ScheduledReminder

An owned, project-oriented reminder with:

- user, project, and optional subproject;
- message;
- cadence: once, daily, or weekly;
- schedule timezone, local anchor date/time, and next UTC fire instant;
- active/cancelled state plus last-fired and snoozed metadata;
- optimistic version for edit/snooze/cancel races.

Project ownership and active/paused project eligibility are enforced on create
and edit. A stopped, archived, or deleted project cannot acquire a new
schedule. Project deletion cascades its schedules. Recurring schedules skip
missed occurrences rather than sending a catch-up burst.

Snooze choices are 15 minutes, 1 hour, or tomorrow at the schedule's local
time. Snoozing changes the next occurrence only; after it fires, a recurring
rule returns to its regular local cadence.

### Commitment opt-in

Add `notifications_enabled` to each commitment, default false. Both the global
commitment preference and this per-commitment switch must be enabled before an
event is created.

### Notification events

Extend event types with `scheduled_reminder`, `commitment_check`, and
`weekly_review`. Stable dedupe keys are:

- `scheduled:<schedule id>:<whole-second occurrence>`;
- `commitment:<commitment id>:<generation>:<period start>`;
- `weekly-review:<user id>:<local week start>`.

Payloads may include a bounded list of same-origin action labels/URLs. The push
serializer keeps the existing strict payload-size cap and never exposes private
configuration. Actions are validated when the event is created (at most two,
bounded labels, and allowlisted relative URLs), and every event carries a stable
tag so unrelated notifications cannot collapse into one browser notification.

`NotificationEvent` has nullable source relations for scheduled reminders and
commitments. Cancelling or editing a schedule cancels any still-pending event
for its superseded occurrence. An event already leased for provider delivery
may win the race and arrive; its destination remains a safe, owned Autumn page.

## Scheduling semantics

Each dispatcher pass runs, in order:

1. expired timer sweep;
2. timer reminder claims;
3. standalone scheduled-reminder claims;
4. due commitment-check preference claims;
5. due weekly-review preference claims;
6. outbox delivery.

All claims use short database transactions, conditional updates, and unique
event keys. No database transaction remains open during provider I/O.
`run_dispatch_pass` keeps its existing public return shape by returning all
newly claimed events in the existing combined `claimed` collection, so the
management command and daemon thread remain compatible.

### Commitment becoming actionable

At the user's configured local check time, inspect active opted-in commitments.
Send at most one event per commitment period when the target is incomplete and
the period is within its final action window:

- daily: final 6 hours;
- weekly and fortnightly: final 2 local days;
- monthly: final 3 local days;
- quarterly and yearly: final 7 local days.

The configurable check time is constrained to 18:00 through 23:59 local so a
daily commitment always has a check slot inside its final six-hour window.

The body reports the exact remaining minutes/hours or session count and a
profile-local deadline label. Completed commitments stay silent. Banking is
respected after reconciling the commitment: when banking is enabled, the open
period is covered when `actual + max(0, balance) >= target`; otherwise it is
covered when `actual >= target`. No warning is sent when covered. Reconciliation
and progress evaluation run under the commitment revision's frozen timezone,
including when it differs from both the profile and server timezones.

### Weekly review

At the configured weekly slot, summarize the seven completed local calendar
days immediately preceding that slot:

- total tracked duration;
- distinct projects with completed sessions;
- number of eligible commitments met and total eligible commitments.

The commitment score is based on periods that actually closed inside the
reviewed seven-day window, not on newly reset current periods. An active
commitment is eligible when at least one canonical period closed in the window;
it counts as met only when every such due period was met after banking. This
makes seven daily periods a genuine weekly result, counts a weekly commitment's
completed week once, and leaves longer-cadence commitments out of the denominator
on weeks where no period ended. Reconcile before reading closed period rows.

Persist only the deduplicated notification event; the review page recomputes
the selected week from authoritative sessions and commitment logic. Empty
weeks may still produce a short neutral review when the user explicitly opted
in.

## Delivery observability

Each outbox event writes a searchable `notification_dispatch` INFO record
through `core.services.push`. The record includes the event and user identity,
event type, scheduled time, overall status, targeted-device count, per-device
delivered/pending/failed/expired/unavailable counts, attempt count, and
`provider_accepted_at`. Provider failures additionally write
`notification_device_failure` WARNING records with the subscription ID,
provider status, and attempt number. Endpoints and payload bodies are never
logged. A delivered count means the push provider accepted the request; it
does not guarantee that a browser or operating system displayed it.

## Web UI

Add a **Notifications** workspace page linked from the More menu. It contains:

- browser delivery status and the existing enable/test/turn-off controls;
- three independent category controls;
- commitment-check and weekly-review local schedule controls;
- a compact create form for project, optional subproject, date/time, cadence,
  and message;
- active schedules with next occurrence and Edit, Snooze, and Cancel actions.

Add a weekly-review page with the summary figures, per-project time, commitment
status, and direct links to Start Timer, Sessions, and commitment detail.

The Start Timer page accepts an owned project/subproject query parameter so
notification actions can prefill it without starting anything. The commitment
form exposes its per-commitment notification toggle only when global commitment
checks are enabled, while preserving the saved value when the global category
is paused.

The service worker renders notification action buttons where supported and
uses the primary URL as a fallback. Clicking Snooze opens a confirmation page;
the POST that changes the schedule remains authenticated and CSRF-protected.

## Verification

- Migrations, constraints, ownership, authentication, CSRF, and optimistic
  version tests.
- One-shot/daily/weekly scheduling, local-wall-time DST, missed occurrence,
  snooze, edit, cancel, and concurrent claim tests.
- Commitment time/session bodies, action-window boundaries, banking/completion
  silence, per-period dedupe, disabled category, and cross-user tests.
- Weekly local-date boundaries, duration/project totals, mixed-cadence closed
  commitment counts, empty-week behavior, disabled category, and dedupe tests.
- Profile timezone different from server timezone, revision timezone different
  from profile timezone, and recurring DST gap/fold resolution tests.
- No-provider/no-subscription terminal behavior and bounded action payloads.
- Service-worker action routing, URL allowlist, and JavaScript syntax checks.
- Focused suites, full Django suite, migration check, and localhost Computer
  Use walkthrough at desktop and narrow widths.
