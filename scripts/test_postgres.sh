#!/usr/bin/env bash
# Run the Django tests against a local PostgreSQL, like CI's Ubuntu job.
# Some failures only show on Postgres (CI and production run it; local runs
# default to SQLite).
#
# Needs PostgreSQL binaries, for example the EnterpriseDB "binaries" zip for
# Windows, unpacked anywhere. No install or service is required: this starts
# the server on 127.0.0.1, runs the tests and stops it again.
#
#   PG_BIN=/path/to/pgsql/bin PGDATA=/path/to/pgdata scripts/test_postgres.sh [test labels/args]
#
# PGDATA is created on first use. Optional: PG_PORT (default 5433), PYTHON
# (default python; use the venv's interpreter).
set -euo pipefail

: "${PG_BIN:?Set PG_BIN to the PostgreSQL bin directory}"
: "${PGDATA:?Set PGDATA to a data directory (created on first use)}"
PORT="${PG_PORT:-5433}"
PY="${PYTHON:-python}"
URL="postgres://postgres@127.0.0.1:${PORT}/autumn"

cd "$(dirname "$0")/.."

if [ ! -f "$PGDATA/PG_VERSION" ]; then
  "$PG_BIN/initdb" -D "$PGDATA" -U postgres -A trust -E UTF8 --no-locale > /dev/null
fi

started=0
if ! "$PG_BIN/pg_ctl" -D "$PGDATA" status > /dev/null 2>&1; then
  # Output goes to the server log, so the server holds no pipe of this shell.
  "$PG_BIN/pg_ctl" -D "$PGDATA" -o "-p $PORT -c listen_addresses=127.0.0.1" \
    -l "$PGDATA/server.log" -w start > /dev/null 2>&1
  started=1
fi
stop_server() {
  if [ "$started" = 1 ]; then
    "$PG_BIN/pg_ctl" -D "$PGDATA" stop -m fast > /dev/null 2>&1 || true
  fi
}
trap stop_server EXIT

export DATABASE_URL="$URL"
# Settings load .env over the environment: refuse to run unless Django
# really resolved this local server (a DATABASE_URL in .env would win).
host=$("$PY" manage.py shell -c "from django.conf import settings as s; d = s.DATABASES['default']; print(d.get('HOST', ''), d.get('PORT', ''))" 2> /dev/null | tail -1)
if [ "$host" != "127.0.0.1 $PORT" ]; then
  echo "Django resolved database host '$host', not 127.0.0.1 $PORT; check .env for DATABASE_URL." >&2
  exit 1
fi

"$PY" manage.py test --noinput "$@"
