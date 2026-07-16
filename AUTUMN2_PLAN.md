# Autumn 2.0 — Evolve-in-Place Architecture Plan (v6 — FINAL)

Status: FINAL after 5 adversarial review rounds (gpt-5.6-sol, high reasoning, both repos inspected each round). No code written in this phase.

> **DECISION UPDATE (2026-07-16, Henry):** Autumn has no external users — single-user install, all clients (CLI, MCP, web) controlled by the maintainer and upgraded in lockstep. Consequences:
> - **v1 API endpoints are removed slice-by-slice** as soon as the corresponding CLI/MCP/web consumer migrates (same release) — no one-release deprecation window, no Deprecation/Sunset headers, no capability advertisement beyond a trivial version field, no daemon terminal-error pre-shipping. S12 shrinks to the physical column drops.
> - **Raw contract goldens** are kept only in their already-narrow form (shapes consumed by CLI, web charts, MCP) and only for the window before each consumer migrates; after migration they are deleted, not maintained. The semantic characterization harness remains fully in force — it protects data correctness, not compatibility.
> - **N−1 rollback CI ceremony dropped**; retained safety: DB backup before every migration, reversible-while-additive migrations, one restore rehearsal before destructive drops.
> - **v1-write-rejection on partitioned sessions (§2.2) becomes moot** if v1 session-edit endpoints are removed before the partitioned flag flips (S10c after S9) — implement only if that ordering changes.
> - Everything preserving **historical data semantics** (`legacy_full`, opening adjustment, backfills) is unaffected — that machinery serves data fidelity, not compatibility.

## Changelog

- **v6** (final; resolves the four round-5 blockers): **commitment replay made fully deterministic** — replay is a single ordered stream of adjustment-apply and period-close events by effective instant (ties: adjustments first; adjustments modify the running balance unclamped; clamping+truncation happens only at period close, as today); **pre-anchor history is immutable** — edits to sessions whose periods closed before `ledger_start_at` never change balances (the opening adjustment is the accounting cutover; v2 returns a warning field when such an edit is detected); **restart lifecycle fully specified** — restart at instant T reuses the same Commitment row with a new `generation` (periods unique on `(commitment, generation, period_start)`): the in-progress partial period is discarded (never closes, accrual in it is not banked), any pending revision is discarded, balance carry is the user's explicit keep-or-reset choice (`restart_carry` adjustment at T or nothing), the new generation's boundaries derive from T's local date in the (possibly new) timezone exactly as a freshly created commitment would, and `ledger_start_at` moves to T; **field-by-field commitment edit policy table** added (restart-only: target identity, aggregation type, time↔sessions type, timezone, cadence, start_date; next-boundary + coalesced: target value, caps, banking, filters; immediate: deactivate, which freezes the ledger — reactivation is a restart; every edit bumps `version`); **v1 representation contradictions fixed by making raw current goldens normative per endpoint** — `tally_by_subprojects` stays an unrounded float exactly as today, v1 `hierarchy` stays non-additive with NO residual child (v1 children may sum to less than the parent for partitioned sessions; documented), partitioned residual appears in v1 only where a "no subproject" bucket already exists today; **format-2 canonical equality tuple completed** — adds `allocation_mode`, instants normalized to UTC whole seconds before comparison, notes normalized (`null ≡ ""`), allocation entries compared as a sorted set of `(resolved subproject name, bp)` with exact case-sensitive name matching, project by resolved scoped name; **retry/If-Match precedence defined** — terminal-state dedup (identical re-stop, already-absent delete) is evaluated BEFORE version validation so a lost-response retry with a stale version still succeeds, while `If-Match` remains mandatory whenever the mutation would change state; CLI retry eligibility is an explicit operation whitelist with UUID/state preconditions, not an HTTP-verb list. Implementation gates carried from review notes: the N−1 nullable-or-default rule applies to EVERY additive column (`version`, `Profile.timezone`, `needs_recompute`, `ledger_start_at`, `generation`, …) with real N−1 writes exercised in CI; write-path closure is proven by an inventory test matrix (web forms, v1/v2 API, admin forms/actions/bulk, importers, management commands, merges/deletes, context/tag M2M changes, queryset deletes) verifying invalidation happens in the mutation's transaction.
- **v5** (after round 4 — closing specification gaps; no architecture changes): commitment replay got an explicit **anchor** (`ledger_start_at` aware instant; opening/restart adjustments carry effective instants; recompute row-locks the commitment and clears the flag in the same transaction; `dirty_from` date simplified to boolean `needs_recompute`; `accrued_minutes`/`applied_delta` dropped as derivable); **timezone/cadence are frozen per commitment lifetime** (changing them = explicit destructive "restart from now" — eliminates bridge/short-period topology entirely; other definition edits queue to next boundary with **one pending revision per commitment, coalescing edits until activation**); added the **version-specific representation matrix** (v1 shapes byte-stable: residual folds into v1's existing "no subproject" projection, `legacy_overallocated` is v2-only, `/api/totals/` and chart-hour units documented as-is; v2 canonical = minutes 2dp); **timestamp normalization = floor to whole second** (monotonic → no start/end inversion); format-2 identity completed (**UUID unique per (user, uuid)**; canonical content equality defined; `force` = in-place update via SessionMutationService preserving server ID and bumping version; **batch import atomic**); exact through-table metadata completed (`id` PK + composite unique + both single-column indexes; redundant forward index benchmarked for drop; **auto-stop index coupled to the `is_active`→`end_time IS NULL` query migration in the same slice**); slices repaired (**format-2 import moved after through-model adoption; S10 split into commitments / format-2 / partitioned-UX; MCP moved after every surface it consumes; N−1 window guaranteed via nullable-or-persistent-default columns until the contract step**); **CLI wake-retry restricted to GET/HEAD + explicitly idempotent operations** (restart not auto-retried; first-party CLI always sends If-Match on session/commitment mutations); **write-path closure gate** added (admin `list_editable` commitment fields removed/routed through services; web commitment forms call services; `m2m_changed` signal on project tags sets `needs_recompute`; one-commitment-per-target OneToOne invariant explicitly preserved); old detached daemons get a **terminal upgrade error** (clean exit with message on v1 removal, not a retry loop).
- **v4** (round 3 — simplification): recompute-forward derived periods replaced event-sourced accounting; dropped early-close; un-gated partitioned attribution from the ledger; slimmed idempotency (UUID natural dedup), revisions (sessions+commitments), compat, contract tooling (no generated DTOs); filter struct not DSL; endpoint-level attribution contract; merge rules fixed; conflict-safe imports; solo-shippable slices.
- **v3** (round 2): uniform read formula; result matrix v1; merge/import rules v1; in-place M2M adoption; idempotency/revision spec; timezone model; cross-cutting foundation; two harnesses; SessionMutationService + CachedTotalsProjection.
- **v2** (round 1): session_ledger/signals recast; DRF + drf-spectacular; service-first sequencing; allocation matrix; honest backfill; versioned export; kept SubProjects.user; v2 date/tz semantics; narrowed offline journal; characterization-first.

## 0. Context and constraints

Autumn: personal time/project tracker; one Django backend; three clients.

- **AutumnWeb** — Django 5.2 + DRF 3.16 (backend unpinned; CLI has uv.lock), server-rendered + fragment polling, SQLite dev / Postgres prod (host sleeps; `/healthz/`). `core/session_ledger.py` = atomic delta ledger for cached totals; `core/signals.py` aligns `is_active`.
- **Autumn CLI** — Click/Rich; `api_client.py` 57 public methods over both API families; YAML config; TTL caches; name-based aliases/resolvers; detached reminder daemon keyed by server session IDs; wake-retry that currently resends any method after connection/5xx failures.
- **MCP** — `autumn_mcp.py` in both repos, diverged by 76 changed lines.

Constraints: Python/Django/Click; evolve in place; multi-subproject sessions stay; personal/self-hosted/CLI-first/agent-native; non-goals: teams, invoicing, billable rates, admin roles. **Scale honesty:** one maintainer, single-user installs, thousands of sessions — recomputation over event sourcing, service invariants over DB machinery, direct migration over parallel infrastructure, wherever correctness allows.

## 1. Current-state problems (verified)

P1. Cached totals couple every write path; bypass paths (importer, API/web merges, `SubProjects.delete()`, queryset deletes, second management-command importer/exporter, admin) are why the audit subsystem exists. Dev DB: zero drift today.
P2. Bare M2M attribution: full credit per link (tests assert it); no weighting; "no subproject" = zero-link sessions.
P3. Three API surfaces; inconsistent v1 date/tz semantics; sessions-search advertises a `subproject` filter it never applies; tags names-vs-IDs; `?compact=` doubles shapes.
P4. Commitment balance: per-period clamp-then-truncate (path-dependent), mutable int, execution-time `last_reconciled`, streaks re-simulated from zero, definition edits reinterpret history. Targets are OneToOnes (one commitment per target — an invariant to preserve).
P5. Persisted-but-derivable state (`is_active`, `crosses_dst_transition`); long consumer tail; drops deferred to contract step.
P6. Wake-retry resends POST/DELETE with no dedup.
P7. Hand-synced clients/docs; two divergent MCP copies; unpinned backend deps.

## 2. Foundational decisions

### 2.1 Attribution: one read formula; mode as write policy

Existing through table (recorded exactly): `core_sessions_subprojects(id PK, sessions_id, subprojects_id)`, composite unique `(sessions_id, subprojects_id)`, plus single-column indexes on `sessions_id` and `subprojects_id`.

```
SessionSubproject: in-place adoption of that table (db_table/db_column preserved, incl. id PK)
  + allocation_bp INT, persistent DB default 10000, CHECK 1..10000
Sessions.allocation_mode ENUM('legacy_full','partitioned'), persistent DB default 'legacy_full'
Sessions.uuid UUID, nullable during migration window, UNIQUE(user_id, uuid); NOT NULL at contract step
```

- Zero-bp links illegal (membership = credit). Backfill: links → 10000; sessions → `legacy_full`.
- **One read formula:** link credit = `duration × bp / 10000`; residual = `duration × max(0, 10000 − Σbp) / 10000`; project credit = full duration. Legacy Σ>10000 → per-link full credit, residual 0 — today's numbers exactly.
- Mode governs writes: `partitioned` = Σ ≤ 10000, links 1..10000, complete-set replacement in one service op under session row lock (no per-link PATCH), even-split remainder → lowest subproject ID. `legacy_full` links always 10000.
- **Numeric contract:** v2-created/edited timestamps **floored to whole seconds** (floor is monotonic → cannot invert start/end; `end ≥ start` re-validated after normalization anyway). One-time migration floors existing fractional rows. Canonical numerator = `elapsed_whole_seconds × bp` (BIGINT; overflow margin ≫ 2⁶³). **Aggregate numerators first, divide once per result cell**; per-surface rounding per §2.2 matrix. Fixtures assert additivity from the numerator level.
- Partitioned mode ships behind a feature flag, **independent of commitments work**; until derived periods (S10a) exist, retroactive allocation edits inside closed banked periods are rejected with an explanatory error (temporary write restriction, not a gate).

### 2.2 Attribution result contract — version-specific representation matrix

Semantics (both API versions compute from the same numerators):

| Consumer | Attribution rule |
|---|---|
| Project totals/series (line/stacked/cumulative), calendar daily totals, context/status/tag tallies, `projects_with_stats` | full session duration |
| Subproject totals/series/scatter | Σ link credit + residual |
| Hierarchy | project = full; children = link credit; residual child when > 0 |
| Histogram / session counts | 1 per session, never fractionalized |
| Heatmap | intervals |
| Wordcloud | notes |
| Time commitments | subproject-targeted: link credit; project/context/tag: distinct-session minutes (today's rule) |
| Session-count commitments | 1 per matching session (separate integer count) |
| Filters everywhere | membership predicates, never weights |

Representation:

| Surface | Contract |
|---|---|
| **v1 — all endpoints** | **raw current goldens are normative**: the golden captured from today's behavior defines the byte-level contract per endpoint; where this matrix and a golden disagree, the golden wins |
| **v1 `tally_by_subprojects`** | shape byte-stable `{"name", "total_time"}` (unrounded float, exactly as today); partitioned residual joins the **existing "no subproject" bucket** (present today for zero-link sessions); no new fields |
| **v1 `hierarchy`** | byte-stable; **stays non-additive: NO residual child** (emits actual SubProjects only, as today); for partitioned sessions children may sum below the parent — documented, not patched |
| **v1 `/api/totals/`** | byte-stable (minutes, `round(...,4)` as today) |
| **v1 `chart_data` variants** | keep current units (hours where hours today), byte-stable |
| **v1 session writes touching subproject relations** | rejected on `partitioned` sessions with explicit "upgrade client" error; all other v1 writes unaffected |
| **v1 reads generally** | same formula → correct numbers, unchanged shapes (legacy data reproduces today's outputs exactly; goldens enforce) |
| **v2 everywhere** | canonical `*_minutes` decimal(2dp); residual identity `{"kind":"residual","project_id":N,"id":null,"name":null}`; `legacy_overallocated: true` metadata where legacy children exceed a parent; additivity invariant fixture-tested for partitioned data |

### 2.3 Merge / rename / delete / import identity

- **Subproject merge (A+B→M)** per session: `legacy_full` → one 10000 link (today's collapse). `partitioned` → `bp_M = bp_A + bp_B (+ existing bp_M)`; cannot exceed 10000 on valid data; **precondition audit** fails invalid sets before merging (no cap branch).
- **Project merge**: subproject name collisions keep today's rename-both-survive behavior; links follow renames unchanged.
- **Commitments on merged-away/deleted targets**: operation rejected until user re-points or deletes the commitment (target FKs move from CASCADE to PROTECT semantics via service checks). One-commitment-per-target (OneToOne) invariant preserved.
- **Rename**: IDs stable; no allocation effect.
- **Import identity (format 2)**: session `uuid` **unique per (user_id, uuid)** — the same portable dataset can import into two accounts on one install. **Canonical content equality tuple** (client-owned fields only; server id/version/server-timestamps excluded): start/end instants normalized to **UTC whole seconds**; note normalized with `null ≡ ""`; `allocation_mode`; allocations as a **sorted set of `(resolved subproject name, allocation_bp)`** with exact case-sensitive name matching; project by resolved scoped name. Same UUID + equal → no-op; same UUID + different → conflict error unless `force`; `force` = **in-place update through SessionMutationService** (server ID preserved, `version` bumped). Duplicate UUIDs in one batch → reject batch. **Format-2 batch validate+import is atomic** (one transaction). Tuple matching (2-min tolerance) legacy-format-only. Scoped-name resolution fails hard on ambiguity.

### 2.4 Date/timezone

- `Profile.timezone` (validated IANA; migration snapshots server tz). Profile edits effective **immediately** for UI/search/reports (request middleware with guaranteed cleanup; domain functions take explicit `ZoneInfo`).
- **Commitments freeze timezone AND cadence for the commitment's lifetime** (set at creation from profile tz). Changing either = explicit destructive **"restart commitment from now"** (closes history at an explicit aware instant, new revision chain, user chooses balance carry: keep / reset). No bridge periods, no short periods, no cutover topology.
- Other definition edits (target value, caps, banking, filters) queue to the **next natural boundary**: at most **one pending revision per commitment** (DB-enforced); further edits before activation **coalesce into it**.
- v2 date ranges: [start 00:00, end+1d 00:00) user tz; bucketing by `end_time` ("completed on"). Interval-splitting = future opt-in param. v1 untouched.

### 2.5 API v2 (DRF + drf-spectacular)

- Pinned backend deps (CLI lock refreshed/validated). Committed OpenAPI artifact, CI fail-on-diff. Handwritten `AutumnClient` façade + contract tests; no generated DTOs.
- Error envelope for handled v2 errors (DRF handler + v2-scoped middleware for 404/405); no global-500 promise.
- **Concurrency:** integer `version` on sessions and commitments. `If-Match` optional in the API contract but **the first-party CLI always sends it** for session/commitment mutations; stale → 409 + current state.
- **Dedup without an idempotency table:** create/track/import dedup via session `uuid`; timer start accepts optional client UUID; deletes: already-absent = success; stop: re-stop = success returning state. **Precedence rule: terminal-state dedup is evaluated BEFORE version validation** — a retry of an identical stop (or a delete of an already-absent resource) succeeds even with a stale `If-Match`, because the requested end state already holds; `If-Match` is enforced whenever the mutation would actually change state. **CLI retry eligibility is an explicit operation whitelist with UUID/state preconditions** (GET/HEAD; UUID-carrying create/track/import; stop; delete) — not an HTTP-verb rule; **timer restart is NOT auto-retried** (surfaced to the user on ambiguous failure).
- Resources: `me`, `timers`, `sessions`, `projects`, `subprojects`, `contexts`, `tags`, `commitments` (+ periods), `reports/*`, `export`, `import`. IDs for writes; names display/resolution. Sessions expose `uuid`, `version`, `allocation_mode`, `subproject_allocations`. Limit/offset + stable ordering + id tie-breaker; `total`/`count`. `include=note` opt-in. No `compact` (MCP adapter compacts). Explicit units.
- **Compat (lean):** `/api/v2/me/` → `{"api_version": 2, "capabilities": [...]}`. v1 lives one migration release beyond full first-party migration; removed in a declared major release; removed known v1 paths then return an actionable "upgrade autumn-cli" error. **Old detached reminder daemons:** on that error the daemon exits cleanly with a logged terminal upgrade message (shipped into the daemon in the CLI-migration slice, one release before v1 removal) — no retry loop.

### 2.6 Commitments: derived periods, recompute-forward

```
Commitment: + needs_recompute BOOL, + ledger_start_at TIMESTAMPTZ (replay anchor),
            + generation INT DEFAULT 1
CommitmentRevision(commitment FK, generation INT, effective_from_instant TIMESTAMPTZ,
    status(pending|active),
    aggregation_type, target ids + display names, filters snapshot (IDs),
    commitment_type, cadence, target, banking_enabled, max_balance, min_balance,
    start_date semantics, timezone)
    -- append-only; at most one pending per commitment (partial unique); edits coalesce into pending
CommitmentPeriod(commitment FK, generation INT, revision FK, period_start, period_end,
    accrued_numerator BIGINT, session_count INT,
    carryover_in INT, balance_out INT, closed_at)
    unique(commitment, generation, period_start)  -- derived snapshots, recomputable
CommitmentAdjustment(commitment FK, seq, kind('opening','restart_carry','manual'),
    amount INT, effective_at TIMESTAMPTZ, reason)
    unique(commitment, seq)
```

- **Replay protocol (deterministic):** recompute locks the commitment row (`select_for_update`) and replays a **single ordered stream of events** — adjustment-applications and period-closes, ordered by effective instant, **adjustments first on ties**. `opening`/`restart_carry` **initialize** the running balance; `manual` **adds** to it; adjustments are applied **unclamped** — clamping (min/max caps) and truncation happen **only at each period close**, exactly as today's math. Only periods of the current `generation` ending after `ledger_start_at` replay. Period rows are inserted/updated and `needs_recompute` cleared **in the same transaction**. Concurrent mutations that set the flag after the lock window simply trigger the next recompute.
- **Pre-anchor history is immutable.** A mutation touching only periods that closed before `ledger_start_at` (or a prior generation) never changes balances — the opening/restart adjustment IS the accounting cutover. v2 responses flag such edits with a warning field (`"commitment_history_unaffected": true`) so the user knows; if they want history rebuilt, that is what restart is for.
- **Restart lifecycle ("restart from now" at instant T):** same Commitment row, `generation += 1`. The in-progress partial period is **discarded** (never closes; its accrual is not banked). Any pending revision is **discarded**. Balance carry is the user's explicit choice: keep → `restart_carry` adjustment (amount = last `balance_out`) effective at T; reset → no adjustment. A new active revision (possibly with new timezone/cadence/target identity) becomes effective at T; the new generation's period boundaries derive from T's local date in the revision's timezone **exactly as a freshly created commitment's would** (reuses the existing start-date period math). `ledger_start_at` ← T. Prior-generation periods remain readable as history. The one-commitment-per-target OneToOne invariant is untouched (same row).
- **Field-by-field edit policy** (every edit bumps `version`):

| Field | Policy |
|---|---|
| target identity, aggregation type, commitment type (time↔sessions), timezone, cadence, start_date | **restart-only** |
| target value, max/min caps, banking_enabled, include/exclude filters | **next-boundary**, coalesced into the single pending revision |
| active → false (deactivate) | **immediate**; ledger freezes (no period closes, no accrual) |
| active → true (reactivate) | **restart** (new generation at reactivation instant) |

- Any historical mutation within the current generation and after the anchor (session edit/delete/move, allocation change, project context/tag change, merge, import, scope change) sets `needs_recompute = true` in the mutating service's transaction. Full replay is milliseconds at this scale; no events, no outbox. Recompute runs lazily on next commitment read (as reconcile does today) or on demand.
- **Migration:** `ledger_start_at` = cutover instant; `generation` = 1; one `opening` adjustment (current `balance`, effective at cutover). No synthetic history; pre-cutover accrual lives only in the opening adjustment (never double-counted). `last_reconciled` → latest closed `period_end`.
- **Write-path closure (gate for S10a):** every commitment writer goes through the revision service or becomes read-only — Django admin `list_editable`/bulk edits on commitment fields removed (admin becomes read-only for definition fields), web commitment forms call the service, `m2m_changed` on project tags sets `needs_recompute`. Inventory: web forms, admin, management commands, import, API, merges, tag M2M changes.
- Revisions snapshot raw IDs + display names (no cascading FKs into history).
- Streaks/history read from period rows. Session-count commitments use `session_count`, never the numerator.
- Target FKs and include/exclude M2Ms stay as storage; the revision snapshot is compiled at revision creation.

### 2.7 Filters (lean)

One small internal filter struct (IDs, include/exclude sets) + shared queryset helpers for v2 search/log/reports/export and commitment scope — fixing the never-applied `subproject` filter and tags names-vs-IDs split. Serialized only inside commitment revision snapshots. Not a DSL. v1 keeps its quirks until removal.

### 2.8 Recorded "no"s

No Projects/SubProjects unification; no `SubProjects.user` removal (constraint/audit instead); no general offline sync; no event sourcing; no early-close/bridge periods (tz/cadence frozen per commitment; destructive restart instead); no generated DTOs; no filter DSL / M2M→JSON migration; no deferred DB triggers; no zero-bp links; no per-link PATCH; no silent commitment retargeting; no auto-retry of non-idempotent mutations; no physical drops before the contract step; audit endpoints return explicit deprecation notices, never silent success.

## 3. Program: solo-shippable slices

Per-slice gates: semantic characterization suite (cloned DB, frozen time, side-effectful reads snapshot/restored) + raw contract goldens **only for shapes consumed by CLI, web charts template, MCP** + migration invariants (row/link counts, ownership checksums, total parity). Rollback: N−1 app against expanded DB — **guaranteed by keeping new columns nullable or persistent-DB-default until the contract step** (`allocation_bp` default 10000, `allocation_mode` default `legacy_full`, `uuid` nullable); reverse-migration test while additive; one backup-restore smoke rehearsal before the destructive release.

- **S0. Foundations** — pin backend deps; both suites; §2.1–§2.4 fixtures; preflight introspection recording exact through-table metadata (id PK, composite unique, both single-column indexes) on SQLite + Postgres.
- **S1. SessionMutationService** — create/track/edit/stop/delete/link-set-replacement around the current ledger's transaction/locking; `CachedTotalsProjection` isolated. Whole-second flooring for new writes + one-time floor migration.
- **S2. Destructive services** — merge/rename/delete via services (§2.3), covering `SubProjects.delete()`, queryset deletes, PROTECT-style commitment-target checks.
- **S3. Import consolidation + session UUID** — one importer implementation (web/API/management command); `uuid` column + backfill (nullable). Format-1 only at this point.
- **S4. Through-model adoption** — SeparateDatabaseAndState over the existing table; `allocation_bp` (persistent default) + `allocation_mode`; backfill; validate (≈3,357 links / 327 multi-link); CHECK added. Additive only.
- **S5. Weighted reads + index/query migration** — uniform formula behind existing serializers; shadow-compare; v1 goldens. Index work paired with its query changes: active/auto-stop scans move from `is_active` to `end_time IS NULL` **in this slice**, with `(user_id, start_time, id) WHERE end_time IS NULL` and `(user_id, auto_stop_at, id) WHERE end_time IS NULL AND auto_stop_at IS NOT NULL`; completed-range indexes `(user_id, end_time, id)` and `(user_id, project_id, end_time, id)` benchmarked on Postgres before dropping predecessors; redundant forward `sessions_id` single-column index benchmarked for drop (composite covers it). CONCURRENTLY via non-atomic migrations; separate SQLite ops.
- **S6. Derived totals — reads** — all `total_time` consumers (serializers, admin, context/tag pages, templates, import validation, export command, project lists, merges, `projects_with_stats` dual fields) → aggregates behind unchanged v1 shapes; benchmark. `start_date` documented as retained mutable legacy metadata; `last_updated` = latest activity (derived).
- **S7. Derived totals — contract** — projection retired; audit subsystem deleted; `/api/audit/` + CLI `audit` → explicit "deprecated: totals always derived"; `total_time` columns dropped one release later.
- **S8. v2 plumbing + timers/sessions slice** — profile tz + middleware + ZoneInfo lib; filter struct; `version` on sessions; envelope; spectacular + CI gate; timers/sessions with UUID dedup. **CLI migrates this slice in the same release** (façade → v2, ISO, envelope-aware errors, If-Match always, narrowed retry policy, versioned local caches). Every later server slice ships with its CLI migration.
- **S9. v2 slices: projects/subprojects → reports → contexts/tags** — server + CLI per slice; web charts template moves in the reports slice; `_chart_date_param` deleted then.
- **S10a. Commitments** — `version` on commitments; revisions/periods/adjustments/anchor per §2.6; write-path closure gate; streaks from rows; opening adjustment.
- **S10b. Export/import format 2** — envelope, UUID identity + conflict rules (§2.3), atomic batches; CLI default format 2, heritage format behind `--legacy` (lossiness warning).
- **S10c. Partitioned attribution UX** — feature flag on; even-split UX in CLI/web; v1 relation-write rejection active. (Before S10a, retroactive allocation edits in closed banked periods are rejected; after, they recompute.)
- **S11. MCP consolidation** — one packaged implementation on v2 (after every surface it consumes: S9 + S10b), adapter-side compaction, `compact` args removed; replaces both copies.
- **S12. Contract** — one migration release after S11 with v1 intact → declared major release removes v1; physical drops (`is_active`, `crosses_dst_transition`, mutable `balance`, deprecated fields, `uuid` NOT NULL); daemon terminal-upgrade-error already shipped (S8/S9 CLI releases); backup-restore rehearsal precedes.

Ordering: S1–S3 → S4–S5 → S6–S7; S8+ after S5 (S6/S7 can interleave); S10a before S10c; S11 after S9+S10b; S12 last.

## 4. Follow-on programs

1. Calendar/timeline week view (session `version`/If-Match).
2. Weekly review (llm_insights → data-grounded retro vs commitment periods).
3. CLI offline journal, narrow (track-only v0, per (account, base_url), explicit `autumn sync`, UUID dedup, intended timestamps, no auto-flush, failures surfaced, no destructive ops).
4. Commitment nudges (derived periods + daemon rework).
5. Interval-split reporting option.

## 5. Import/export

Format 2: `{"format": 2}`; sessions `uuid`, `allocation_mode`, links `{subproject: scoped name, allocation_bp}`. Importer accepts 1 and 2 (format-1 → 10000/`legacy_full`; tuple heuristic legacy-only). Conflict/atomicity per §2.3. Import runs through services (sets `needs_recompute` where relevant).

## 6. Risks

R1. M2M adoption state drift — preflight metadata + SeparateDatabaseAndState + goldens.
R2. v1 byte-compatibility while re-plumbing — targeted goldens per slice.
R3. Aggregate performance on free-tier Postgres — S5/S6 benchmarks before contract; rollup projection escape hatch.
R4. Commitment replay correctness — single implementation, fixture-tested against current reconcile outputs incl. the +1000/cap600/−500 path-dependence case and anchor/no-double-count cases.
R5. Old daemons/MCP — v1 lives one release past full migration; daemon terminal-error shipped ahead; MCP consolidation blocks contract.
R6. Scope creep — §2.8 + §4.

## 7. Implementation gates (carried from review — not plan blockers, but required during build)

G1. The N−1 nullable-or-persistent-default rule applies to **every** additive column (`version`, `Profile.timezone`, `needs_recompute`, `ledger_start_at`, `generation`, `uuid`, `allocation_bp`, `allocation_mode`); CI exercises real N−1 writes against the expanded schema.
G2. Write-path closure proven by an inventory test matrix: web forms, v1/v2 API, admin forms/actions/bulk edits, importers, management commands, merges/deletes, project context changes, tag M2M changes, queryset deletes — each either calls the owning service or is read-only, and invalidation occurs in the mutation's transaction.
G3. Raw goldens captured per consumed v1 endpoint **before** each slice that touches it; goldens are the normative contract.
G4. Commitment replay fixtures include: the +1000/cap600/−500 path-dependence case; adjacent adjustment/period-close tie ordering; restart with keep vs reset carry; DST-crossing periods; pre-anchor edit no-op with warning flag.

## 8. Review provenance

Five adversarial review rounds (Codex CLI, gpt-5.6-sol, high reasoning effort, both repos inspected read-only each round; ~250–275k tokens per round). Round 1: 19 findings (4 blockers) — corrected the plan's model of the codebase, killed django-ninja, forced service-first sequencing. Round 2: 17 findings — uniform read formula, epoch'd definitions, in-place M2M adoption, cross-cutting foundation. Round 3: gold-plating purge — replaced event-sourced accounting with recompute-forward, un-gated attribution from the ledger, slimmed idempotency/compat/contract tooling. Round 4: verified the math fix; seven specification gaps. Round 5: four residual blockers (replay determinism, restart lifecycle, v1 golden contradictions, retry/If-Match precedence) — resolved in this v6. Round-5 execution risks to watch: (1) path-dependent replay across restart/adjustment/DST/concurrency boundaries; (2) silent v1 response regressions from weighted aggregation, residual handling, rounding, or join fan-out; (3) SQLite/Postgres migration divergence during through-model adoption, partial indexes, and N−1 rollback writes.
