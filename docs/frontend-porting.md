# Porting a page to the React app

How pages move from Django templates (`core/templates/core/*.html` +
`core/static/core/js/*`) into `frontend/`. Read `docs/ts-react-plan.md` first
for the why. The Sessions page (`frontend/src/features/sessions/`) is the
reference port: copy its patterns.

## Rules

1. **Parity first, same look.** The Night Ledger stylesheet
   (`core/static/core/css/focus_desk.css`) is loaded on every app page. Render
   the same markup and class names the template renders, so the page looks
   identical. Read the template, its partials and its JS before writing
   anything. Do not restyle. New UI may add classes in
   `frontend/src/styles/app.css` using the existing tokens (`--brand`,
   `--raised`, `--hairline`, `--s1..--s8`, `--r-*`, `--fs-*`), never new colours.
   Semantic text colours are load-bearing: projects `.text-red` /
   `.session-project`, subprojects `.sub-chip` / blue, durations green, clock
   times `--time`.
2. **Only `/api/v2/`.** Pages talk to the typed client in `src/api/client.ts`
   (`api.GET/POST/PATCH/DELETE` + `unwrap`). Types come from
   `src/api/schema.d.ts` (generated from `openapi-v2.yaml`; never edit it) via
   aliases in `src/api/types.ts`. If the API lacks something the page needs,
   do NOT add backend code: note it under "API gaps" in your report and use
   the closest workable approach (or leave a clearly marked TODO).
3. **Server state lives in TanStack Query.** Query keys from `src/api/keys.ts`.
   After a mutation call `useInvalidate()` (`src/api/sync.ts`) with the
   topics it affects: it refreshes this tab and every other open tab.
   Lookup data: `useAllProjects`, `useTags`, `useContexts`, `useSubprojects`
   in `src/api/meta.ts`.
4. **Context.** `useActiveContext()` gives the header's context;
   `contextIdsParam` is the value for `context_ids` / `context` API params.
   API endpoints never apply it implicitly: pass it.
5. **URLs.** Use `<AppLink href={urls.x()}>` from `src/app/links.tsx` for
   every internal link (it does client-side navigation for app routes and a
   full page load otherwise). Keep the route paths in
   `src/app/routePatterns.ts`; they match the old Django URLs so bookmarks
   work.
6. **Forms.** Wrap form controls in an element with class `fields` (that is
   where focus_desk.css hangs the input styles). Show field errors from
   `ApiError.fieldMessages()` / `errorMessage()` (`src/api/errors.ts`). After
   a successful save: toast (`useToast()` from `src/app/toasts.tsx`) and
   navigate where the old view redirected. Django `messages` become toasts.
7. **Confirm pages.** Old "Are you sure?" delete pages keep their URL (people
   have them bookmarked) but should be a proper page with the same summary and
   a clear destructive button. Inline actions elsewhere may use
   `ConfirmDialog` (`src/components/Sheet.tsx`). Offer Undo in the toast
   when the API makes it possible.
8. **Shared components** live in `src/components/` (Icon, Sheet, Dialog,
   ConfirmDialog, Disclose, OptionPicker, SessionNote, Skeleton/ErrorState/
   Empty) and `src/lib/format.ts` (durations/dates matching the template
   filters). Do not change their behaviour; if you need more, add a prop in a
   backwards-compatible way and say so in your report, or create a new
   component.
9. **Icons:** `<Icon icon={faX} />` with icons imported from
   `@fortawesome/free-solid-svg-icons` (Font Awesome 5 names, same as the
   templates' `fa-x` classes, camel-cased).
10. **Loading/empty/error states:** `Skeleton`, `Empty`, `ErrorState`. Never a
    blank page.
11. **Accessibility:** real buttons/links, labels for inputs, `aria-current`
    on the active item, focus visible. Dialogs via the shared components.
12. **Tests:** pure logic goes in `src/lib/` or the feature folder with a
    `*.test.ts(x)` next to it (Vitest + Testing Library). Test the logic that
    could be wrong (formatting, grouping, validation, URL <-> state), not
    markup.
13. **No real user data** anywhere (fixtures, screenshots, test strings): the
    repo is public. The dev database holds the fictional "Finrod" account.

## Running it

- Vite: `cd frontend && npx vite` (port 5173, HMR).
- Django with the app: `bash ../ts-react-scratch/run-django.sh 8765` (fictional
  dev DB, DEBUG on, S3 off, loads modules from Vite).
- The pre-port UI for comparison runs from the `ts-react-api` worktree on
  port 8766 (`APP_DIR=.../AutumnWeb-api VITE_DEV_SERVER= bash run-django.sh 8766`).
- Login: `Finrod` / `finrod-dev-pass` (dev DB only).
- Screenshots: `MSYS_NO_PATHCONV=1 node ../ts-react-scratch/shot.mjs <path> <width> <height> <name> [--full]`
  (`BASE=http://127.0.0.1:8766` for the old UI; `ACTIONS='[{"click":"sel"},{"fill":"sel","value":"x"},{"press":"Enter"},{"wait":300},{"eval":"js"}]'`
  to interact first). It prints console errors and failed requests. Compare
  old vs new at 1440x900 and 390x844.
- Checks: `npx tsc --noEmit -p tsconfig.json` and `npx vitest run` in
  `frontend/`. Other agents may be editing other features at the same time:
  only errors in your files are yours to fix.
