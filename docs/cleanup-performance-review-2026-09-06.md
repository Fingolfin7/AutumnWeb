# Cleanup and resource review — 6 September 2026

This review covers AutumnWeb and the adjacent Autumn CLI checkout. The follow-up
implements the approved improvements with a 90-day notification history window.
Visible-tab polling stays at five seconds. See the task completion message for
the verified commit, CI, and deployment state.

## Implemented

| Area | Change | Resource or usability effect |
| --- | --- | --- |
| Browser polling | Stop timer polling and dashboard intervals in hidden tabs; refresh on return | Eliminates up to 720 timer fragment requests and 12 timeline requests per hidden tab-hour, calculated from the old intervals. A request already in flight may finish. |
| Network failures | Timer polling backs off from 5 seconds to at most once per minute | Reduces repeated failed requests; successful requests restore normal cadence. |
| API filters | Share include/exclude ownership checks by model | All seven supported ID filters use four ownership queries. Distinct valid sets and field-specific rejection of foreign IDs are tested. |
| Notification dispatcher | Replace speculative API-name discovery and missing-module fallbacks with the existing claim function | Removes obsolete branches while preserving claim limits, timestamps, durable scheduling, and delivery behavior. |
| Dependencies | Remove unused APScheduler and inflect; move test-only lxml to development requirements | Smaller production dependency set. No measured RAM or build-size saving is claimed. |
| Settings and source | Remove unused audit scheduler settings, commented initialization code, and unused imports | Startup no longer requires the unused AUDIT_PERIOD variable. The manual audit command remains available. |
| CLI help | Group commands by task and show aliases once | Existing command names and shortcuts remain usable. |
| CLI defaults | Bare context and tag commands list entries | Matches the existing commitments default. |
| CLI startup | Reuse the config already loaded by reminder-registry fallback | One config load/deep copy instead of two on that path. |
| CLI documentation | Add an everyday quick start and correct stale command references | Help and documented commands agree. |

Two web tests covering obsolete, hypothetical notification-module interfaces
were replaced by a single test enforcing the live claim budget. Existing
delivery, concurrency, scheduling, authentication, and mutation tests remain.
The CLI review found no clearly redundant tests worth deleting. Additional
regressions now cover resource budgets and optional chart installations.

## Verification

- Web baseline: 706 tests, one skipped.
- Web after all changes: 721 tests, one skipped, using a local SQLite test database.
  Weekly progress fixtures now use a fixed midweek clock, avoiding future
  sessions just after the week begins.
- Five executable JavaScript tests cover hidden tabs, return to visibility,
  overlapping requests, unsaved notes, in-flight responses, and failure backoff.
  These also run in CI using Node built-ins.
- Django system and migration-drift checks pass. Migration 0053 adds an indexed
  completion timestamp for bounded notification retention.
- CLI: 315 tests pass in the base environment; the optional MCP module is
  skipped when its extra is absent. Package compilation and a real chart render
  pass. CI verifies minimal installs on Windows/Linux and the chart extra on Linux.
- Both repositories pass `git diff --check`.
- CLI help startup samples remained around one second. The samples overlap
  enough that they do not establish a reliable speed improvement.

The local tests do not establish production CPU, RAM, transfer, or billing
savings. The request/query reductions above are structural and tested; actual
savings depend on usage. PostgreSQL CI and production verification await a push.

## Hosting snapshot

Read-only Render inspection confirmed the live deployment is commit `d3567a9`,
with one instance, one Gunicorn worker, four threads, and `/healthz/` probes.
The initial local checkout was behind that version and was fast-forwarded
before this cleanup. The existing deadline-aware dispatcher, connection reuse,
and Neon pooled-cursor safeguards were preserved.

Neon reported one Autumn compute, autoscaling from 0.25 to 2 CU, and about
61 MiB of synthetic storage. Its suspend timeout is the default (`0` in the
API), rather than disabled. Neon documents five-minute inactivity suspension;
see [Neon scale to zero](https://neon.com/docs/introduction/scale-to-zero) and
[Neon's API field guidance](https://github.com/neondatabase/ai-rules/blob/main/neon-api-projects.mdc).
This is a configuration snapshot, not a before/after usage measurement.

## Follow-up implementation

- Visible browser polling remains five seconds, as requested.
- Completed notification events and their terminal deliveries are eligible for
  deletion after 90 days. Session data, timer/reminder sources, active events,
  and events with unfinished deliveries are preserved. Migration 0053 starts
  the retention clock for pre-existing terminal history at migration time;
  deployment therefore does not immediately purge old diagnostics.
- Automatic cleanup uses the dispatcher's existing wakeups, at most once per
  process per day, with a default batch of 100 events and a hard cap of 1000.
  It yields to imminent notifications and does not create a new polling thread.
- CLI plotting packages are an optional `charts` extra. Existing environments
  keep installed plotting packages; fresh basic installs avoid them. See the
  CLI README for source-install and chart-upgrade instructions.
- Browser visibility/backoff, API ownership queries, idle notification scans,
  and retention batch/daily limits have executable regression coverage.
- `scripts/resource_snapshot.py` captures bounded Render metrics and Neon
  consumption counters without querying the application database. Snapshots
  go in the ignored `resource-snapshots/` directory. It never writes credentials
  or full account/project responses. Billing-period resets and missing counters
  are treated as unavailable comparisons rather than savings.

## Operating the resource controls

Install development tools with `pip install -r requirements-dev.txt`.
Preview one bounded retention batch without deleting anything:

```console
python manage.py cleanup_notification_history --dry-run
```

Run a batch manually with `python manage.py cleanup_notification_history`.
Configure `NOTIFICATION_HISTORY_RETENTION_DAYS` (default 90; 0 disables cleanup)
and `NOTIFICATION_HISTORY_CLEANUP_BATCH_SIZE` (default 100). A backlog can take
multiple daily passes to clear. Instances that do not run the in-process
reminder dispatcher can run the bounded management command from their existing
maintenance schedule.

Capture a 24-hour Render window and Neon counters with authenticated provider
CLIs (or `RENDER_API_KEY` for Render):

```console
python scripts/resource_snapshot.py --render-service SERVICE_ID --neon-project PROJECT_ID --output resource-snapshots/baseline.json
python scripts/resource_snapshot.py --render-service SERVICE_ID --neon-project PROJECT_ID --output resource-snapshots/follow-up.json --compare resource-snapshots/baseline.json
```

The second command belongs after a comparable measurement period, not immediately
after the first. Provider counters can lag. On Neon's free plan the snapshot uses
current cumulative counters; detailed consumption history is available only on
eligible paid plans. See [Neon consumption metrics](https://api-docs.neon.tech/reference/getconsumptionhistoryperprojectv2)
and [Render metrics](https://render.com/docs/service-metrics).

Pre-deployment snapshots are stored locally in `resource-snapshots/`. A follow-up after
24 hours will compare Render CPU, memory, HTTP volume, and bandwidth, plus Neon
counter changes. Different usage, weekdays, and open browser tabs can affect the
comparison; a single window cannot establish causal billing savings.

Render worker counts and Neon compute limits are unchanged. Raising workers
duplicates in-process dispatchers and connections; lowering compute limits
without workload measurements can slow requests without removing wasted work.
