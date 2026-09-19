# Jev timer recommendations

Jev provides advisory suggestions for a sensible next use of time. It is not
trying to predict what the user will click, and it does not start timers or
change goals. The existing Commitment Push, Usually Now, and Recent Presets
sections remain available, collapsed by default.

## Account and credentials

Save a TypeSafe / Jev key in Profile, under AI connections. It uses the same
encrypted, account-tied storage as the other API keys. AI features must be
enabled for the account. Production never falls back to a shared environment
key. Development may use `TYPESAFE_API_KEY` or `JEV_KEY` when no profile key is
stored. Keys are credentials, not part of the model's context.

## Information shared with Jev

- Current local date, weekday, time, timezone, and selected recommendation
  context. Available time and energy are unknown unless explicitly supplied.
- Completed sessions from the past 30 days across the signed-in account,
  including full notes, timestamps, durations, and project/subproject links.
- Relevant projects and subprojects, including their descriptions. Project
  context, tags, and status provide background without repeating descriptions
  on every session.
- Active commitments, including fulfilled commitments: targets, actual work,
  banked coverage, remaining amounts, period boundaries, time remaining, and
  which candidate timers would count toward them.
- Running timers separately from completed work.
- Monthly year-to-date activity totals for relevant projects, not a year of raw
  notes. An eligible project with no recent history can include its latest
  older session, explicitly marked as older evidence.

History may span this account's contexts, but recommendations are restricted
to the selected context. Another account's data is never intentionally included.
Active projects without recent sessions remain eligible; ongoing timers and
inactive projects are not suggested.

The payload is bounded. When necessary, older complete session records are
omitted rather than cutting notes mid-sentence. Coverage metadata reports
omissions. Project descriptions and other core metadata are not silently
truncated; if essential context cannot fit, Jev advice is unavailable and the
ordinary suggestions remain usable.

The current implementation uses 64,000 UTF-8 bytes for shared state and
160,000 bytes for the whole request as size heuristics, not exact token
counts. The provider's context limit remains authoritative. Older continuity
examples are omitted before recent sessions; recent sessions are then removed
oldest-first. Up to 120 candidate timers can be scored, with any candidate
omissions reported in the payload's coverage metadata.

## How suggestions are chosen

Each candidate receives its own 0–4 suitability score in one batched request
with shared context. Up to three sufficiently supported candidates are shown.
The display threshold is 2 (a reasonable option); scores may be fractional.
Confidence is separate from suitability, so several good choices do not have
to compete for a single probability budget. Jev does not generate UI prose.

Dates, durations, totals, and commitment balances are calculated by Autumn.
Instructions treat session notes and descriptions as evidence, not commands;
prefer newer evidence; respect covered commitments; and avoid guilt, forced
catch-up, or assuming that an old project must be revived.

Requests are optional and load after the timer page. Provider failure leaves
the existing suggestions usable. Recommendations are cached briefly; relevant
context changes invalidate the cache. No live provider call is needed by the
automated tests.
