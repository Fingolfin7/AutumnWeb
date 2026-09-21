# Jev timer recommendations

## Luna comparison

The timer page also shows **Luna Recommends**, alongside Jev on desktop and
stacked on mobile. It uses `gpt-5.6-luna` with `xhigh` reasoning through the
same ChatGPT OAuth connection used by Insights, stored encrypted in Profile.
The shared token helper refreshes and saves renewed credentials when needed.
AI features must be enabled. OAuth is tried first; if it fails, Luna falls back
to the account's saved OpenAI API key, matching Insights. API-only accounts also
work. Neither credential is included in the model's state.

Both providers use the same candidate builder, context builder and bounded
state normalization: recent session notes, project descriptions, commitments,
current time, running timers, older latest sessions and YTD summaries. Luna
also receives the same 0–4 rubric and explicit `no_activity` option. It selects
up to three candidates scoring at least 2, with a short evidence-based reason
and next step. Luna's self-assigned scores are not probability-weighted Jev
scores and should not be interpreted as calibrated across providers.

Requests load independently. Luna allows 120 seconds for OAuth and 60 seconds for
API-key fallback, with no automatic SDK retries and `store=False`. The browser
allows 195 seconds for both attempts. It collects streamed text deltas, including
when the OAuth terminal event omits output, and validates only completed responses.
Logs record the successful auth route or failure category, never response content
or credentials.
Both providers use a database-backed cache shared across server workers and
deploys, isolated by account, provider, and selected context. Each result lasts
30 minutes from completion. A fingerprint change (included project descriptions,
session notes, commitments, running timers, candidate eligibility, or local date)
triggers new advice on the next request. Exact clock and elapsed counters do not
invalidate advice on every visit. There is no continuous background regeneration.
One atomic seven-minute lease per scope deduplicates concurrent requests; waiting
pages retry the fragment without launching another provider call. Failed requests
have a 15-second cooldown, and expired leases can be reclaimed after worker loss.
The Refresh recommendations button expires this account's cached advice without
interrupting an already-running generation. It requires a CSRF-protected POST.
Reasons render as escaped text. IDs and scores are validated and project
ownership, activity status, subprojects and running timers are rechecked before
rendering any start button. A missing key, empty recommendation result, and
provider failure have distinct messages. Neither provider modifies timers.
The comparison remains enabled until explicitly removed; there is no automatic
winner selection or end-of-week removal.

## Usage and cost review

The timer page links to `/timers/recommendation-usage/`, an account-only review
for the last 7 days (or 30 days; `days` accepts 1–90), with a CSV export. The
database ledger records provider attempts separately from cache hits, including
model, effort, OAuth/API route, duration, success/failure category, input/output
tokens, cached input, reported cache writes, and reasoning tokens when available.
An OAuth failure followed by API fallback is two attempts, including any usage
reported before failure. Missing usage or costs remain NULL, never fabricated zero.
No prompt, session-note copy, raw response, credential, or exception text is saved
in the usage ledger. Cached recommendations themselves include their explanations.

Luna stays on **xhigh**. Its cost is an **API-equivalent estimate**, not an OAuth
bill or a prediction of subscription quota consumption. Reasoning is already
included in output tokens and is not charged twice. Pricing snapshots are stored
per attempt so historical estimates do not change when code/prices change.
As checked on 2026-09-22, Luna standard rates per million tokens are $0.20 input,
$0.02 cached input, $0.25 reported cache writes, and $1.20 output; above 272K input
tokens the rates are $0.40/$0.04/$0.50/$1.80. Jev 1.13 input is $0.042/M and
output is free. Sources: https://developers.openai.com/api/docs/models/gpt-5.6-luna
and https://docs.typesafe.ai/models. Unreported cache-write charges are excluded;
totals can undercount failed calls that never return usage. Tracking begins at
deployment; there is no backfill or scheduled weekly report.

Jev provides advisory suggestions for a sensible next use of time. It is not
trying to predict what the user will click, and it does not start timers or
change goals. The existing Commitment Push, Usually Now, and Recent Presets
sections remain available, collapsed by default.

An explicit `no_activity` candidate, shown as “Start nothing for now”, is
evaluated alongside activities on the same 0–4 rubric. It means not starting
a new tracked activity: a break, unstructured time, or continuing an existing
activity are all possible interpretations. It never stops an existing timer
and has no start action. Like activities, it must score at least 2.0 and rank
within the top three to appear. One of the 120 candidate slots is reserved for
this option, including when no eligible projects exist. The model is told not
to assume fatigue or available time.

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
