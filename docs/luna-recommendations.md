# Luna timer recommendations

Luna is the sole external recommendation provider, using `gpt-6-luna`.
The timer Suggestions panel offers High or xHigh reasoning beside Apply & refresh.
The choice is saved per account, defaults to xHigh, and does not affect Insights.
Changing effort requires a CSRF-protected POST and expires only that account's
Luna cache. Effort is also in the cache fingerprint and usage ledger. An active
generation retains its lease; the next request generates with the new effort
after the old lease completes, rather than serving the old-effort result.

## Authentication and behavior

AI access must be enabled. Luna uses the same encrypted ChatGPT OAuth connection
as Insights, then the account's OpenAI API key as fallback. API-only accounts
also work. No global production credential fallback is used.
Responses stream internally; only completed, validated results render. OAuth has
a 120-second timeout and API fallback 60 seconds, without automatic SDK retries.
The browser allows 195 seconds. All supplied evidence is untrusted data, not
instructions. Neither recommendations nor refreshing them starts a timer.

Luna selects at most three bounded candidate IDs, with a suitability score on
the existing 0–4 rubric, an evidence-grounded reason and optional next step.
Scores below 2 are omitted. Fewer than three or no suggestions are valid.
`no_activity` is explicit and never renders a start-timer button. Account
ownership, active status, running timers and subprojects are rechecked before
rendering start buttons. Explanations render as escaped text.
Commitment Push, Usually Now and Recent Presets remain collapsed fallbacks.

## Evidence sent to Luna

`timer_recommendation_context.py` builds account-scoped evidence;
`recommendation_state.py` normalizes it directly for Luna. No TypeSafe SDK,
per-candidate Jev questions or Jev request envelope is constructed.
Evidence remains unchanged: current local date/day/time, selected context,
commitment progress and banking, running timers, complete recent session notes
(30 days), relevant project/subproject descriptions, older latest sessions for
continuity, and year-to-date activity summaries. History is account-wide;
candidate eligibility respects the selected context and excludes running work.
Candidates include active eligible project combinations and `no_activity`.

The existing 64,000-byte serialized evidence ceiling and 120-candidate bound
are preserved. When needed, whole oldest continuity/history records are omitted,
not notes silently truncated; coverage records the omission. Credentials never
enter evidence. Refactoring removes local scoring-question work and obsolete
Jev limit metadata. There is no substantial input-token reduction: Jev questions
were never sent to Luna.

## Caching and measurement

Results persist for 30 minutes from completion, isolated by account and context.
Model, effort, actual evidence changes and local date invalidate the fingerprint;
exact time/elapsed counters do not invalidate on every visit. One seven-minute
lease deduplicates in-flight generation; pending pages retry every five seconds.
Failures have a 15-second cooldown. There is no background regeneration.

The account-only usage page and CSV retain historical Jev and GPT-5.6 records.
Attempts record model, selected effort, auth route, duration, status/category,
reported input/output/cached/cache-write/reasoning tokens and a pricing snapshot.
Cache hits are separate. Missing usage remains unknown. Reasoning is within
output, never added twice. OAuth cost is API-equivalent, not an actual bill or
subscription quota calculation. Logs/ledger contain no prompts, notes, raw
responses, credentials or exception text.

Jev's endpoint, panel, key-entry controls and SDK dependency have been removed.
Its historical usage and dormant encrypted-key database column remain intact;
no runtime path reads that key or calls Jev.
