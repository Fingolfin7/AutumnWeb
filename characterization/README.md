# Characterization harness

This package contains two complementary clone-backed suites. Raw goldens are the
normative byte-level v1 contract required by G3. Semantic goldens parse JSON and
protect computed values independently of response representation. Synthetic
characterization tests live in `core/test_characterization_semantics.py` and run
in CI without personal data.

The clone, metadata, and goldens are local-only and gitignored because they can
contain personal project names, notes, and session times. Never add them to Git.

## One-time setup and capture

Install development dependencies and clone the live SQLite database. The clone
command opens `db.sqlite3` read-only and copies it with SQLite's backup API.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe manage.py chz_clone
$env:AUTUMN_CHZ_DB = (Resolve-Path .\characterization\clone.sqlite3).Path
$env:AUTUMN_CHZ_MODE = "capture"
.\.venv\Scripts\python.exe manage.py test characterization --keepdb
```

```bash
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe manage.py chz_clone
AUTUMN_CHZ_DB="$(pwd)/characterization/clone.sqlite3" \
AUTUMN_CHZ_MODE=capture \
./.venv/Scripts/python.exe manage.py test characterization --keepdb
```

Each clone receives a UUID fingerprint. Re-cloning always requires recapturing
all goldens; comparison deliberately fails when clone and golden fingerprints
differ.

## Per-slice gate

Run compare mode immediately before starting a modernization slice and again
after finishing it. A slice passes only when both the exact raw contract and the
numeric semantic contract remain green.

```powershell
$env:AUTUMN_CHZ_DB = (Resolve-Path .\characterization\clone.sqlite3).Path
$env:AUTUMN_CHZ_MODE = "compare"
.\.venv\Scripts\python.exe manage.py test characterization --keepdb
```

```bash
AUTUMN_CHZ_DB="$(pwd)/characterization/clone.sqlite3" \
AUTUMN_CHZ_MODE=compare \
./.venv/Scripts/python.exe manage.py test characterization --keepdb
```

Tests freeze time at the clone instant, authenticate as the user owning the most
session rows, and use Django `TestCase` transactions. Those transactions roll
back mutation scenarios and side-effectful reads such as commitment reconciliation
and `/api/audit/`. Without `AUTUMN_CHZ_DB`, clone-backed classes skip cleanly.
If the variable is set but the clone or `meta.json` is missing, run `chz_clone`.

The preflight command records the current database vendor's implicit M2M table
metadata. Run it in each database environment; a later PostgreSQL run merges a
`postgresql` section into the same committed file.

```powershell
.\.venv\Scripts\python.exe manage.py chz_preflight
```

> **S12 note:** the raw byte-level golden suite retired with the v1 API. The v2
> contract is guarded by the committed `openapi-v2.yaml` (CI-diffed) and the
> unit suites; this package now carries only the semantic (numeric) suite,
> which runs against the cloned database exactly as before.
