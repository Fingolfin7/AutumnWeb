# Commitments App Extraction Plan

## Goal
Extract commitment-related domain logic from `core` into a dedicated `commitments` Django app, while keeping behavior stable and minimizing migration risk.

## Why
- Commitment logic now spans model design, composable rule evaluation, reconciliation, streak math, and multiple UI surfaces.
- Keeping it in `core` increases coupling with unrelated project/session CRUD flows.
- A dedicated app improves maintainability, test isolation, and future extensibility.

## Target Architecture
- New app: `commitments`
- Ownership:
  - `models.py`: `Commitment` (and future history/snapshot models)
  - `services.py`: progress, streak, reconciliation, applicability checks
  - `forms.py`: commitment create/update forms
  - `views.py`: create/update/delete views if fully moved
  - `selectors.py` (optional): read/query helpers
  - `templates/commitments/...`: commitment pages and reusable partials
- `core` becomes a consumer:
  - Core pages call `commitments.services.*`
  - Core templates include commitment partials rendered from shared context contracts

## Phased Plan

### Phase 0: Prep and Safety
1. Create `commitments` app and add to `INSTALLED_APPS`.
2. Add a temporary compatibility module in `core` (thin wrappers/import forwards) to avoid big-bang breakage.
3. Freeze baseline behavior:
   - Run full `core` test suite.
   - Capture current commitment page screenshots (optional but recommended).

### Phase 1: Extract Domain Logic First (No Model Move Yet)
1. Move the following from `core/utils.py` into `commitments/services.py`:
   - `get_commitment_sessions_queryset`
   - `get_commitment_progress`
   - `calculate_commitment_streak`
   - `reconcile_commitment`
   - `get_commitment_start_datetime`
   - Any commitment-specific applicability helpers currently in `core/views.py`
2. Update imports across `core/views.py` and tests to use `commitments.services`.
3. Keep function signatures stable to reduce churn.
4. Add focused unit tests under `commitments/tests/` and keep existing `core` integration tests green.

### Phase 2: Extract Forms and Templates
1. Move `CommitmentForm` to `commitments/forms.py`.
2. Move commitment pages/partials:
   - create/update/delete commitment templates
   - shared commitments panel partial
3. Update template include paths from `core/...` to `commitments/...`.
4. Keep URLs temporarily in `core/urls.py` if needed, but map to `commitments.views`.

### Phase 3: Extract Views and URL Namespace
1. Move commitment CRUD views into `commitments/views.py`.
2. Create `commitments/urls.py` with namespaced routes (`app_name = "commitments"`).
3. Include commitments URLs from project URLconf.
4. Keep backward-compatible route names initially (or add redirects) to avoid breaking links/templates.

### Phase 4: Move Model (Highest-Risk Step)
1. Move `Commitment` model from `core/models.py` to `commitments/models.py`.
2. Preserve DB table name using `Meta.db_table = "core_commitment"` initially to avoid data copy.
3. For M2M tables, keep existing through-table names where possible to prevent destructive migrations.
4. Generate migrations carefully and inspect SQL before applying.
5. Verify admin registration, related names, and import paths.

### Phase 5: Clean-Up
1. Remove compatibility wrappers from `core`.
2. Remove stale imports and duplicate logic.
3. Split tests:
   - Domain-heavy tests in `commitments/tests/`
   - Cross-page rendering/integration tests in `core/tests.py`
4. Update README/docs with new app boundaries.

## Data and Migration Strategy
- Preferred: table-preserving move.
  - Keep `core_commitment` table name during initial model move.
  - Avoid any immediate table rename.
- If table rename is desired later:
  - Do it in a separate migration after stabilization.
  - Plan explicit downtime/backup and rollback instructions.

## Rollback Strategy
1. Keep each phase in separate PR/commit.
2. After each phase:
   - Run tests.
   - Smoke test create/update/delete commitment flows.
3. If regression appears:
   - Revert last phase only.
   - Keep compatibility wrappers until full migration is proven stable.

## Testing Checklist Per Phase
- Unit:
  - Period boundary correctness (daily/weekly/monthly/etc.)
  - `start_date` behavior (inclusive date anchoring)
  - Include/exclude rule composition
  - Banking/reconciliation correctness across period transitions
- Integration:
  - Dashboard commitment cards
  - Project/subproject/context/tag update pages show correct commitments
  - “Add commitment” deep-link prefilter behavior
  - Links and color mapping by aggregator type
- Regression:
  - Full `core` test suite stays green
  - New `commitments` test suite green

## Suggested Session Breakdown
1. Session A: Phase 0 + Phase 1
2. Session B: Phase 2 + Phase 3
3. Session C: Phase 4 model move + hardening
4. Session D: Phase 5 cleanup + docs

## Optional Improvements After Extraction
- Add explicit period snapshots/history model so dashboard can show reconciled timeline without recomputation.
- Add domain service class instead of free functions if complexity grows.
- Add dedicated API endpoints for commitments UI to reduce view/template coupling.
