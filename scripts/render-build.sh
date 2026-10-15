#!/usr/bin/env bash
# Render build command: `bash scripts/render-build.sh`.
# Installs Python deps, builds the React app into core/static/app/ (gitignored,
# so every deploy builds it), then collects static files. Node comes from
# Render's native runtime; .node-version at the repo root pins the major.
set -euo pipefail

pip install -r requirements.txt

node --version
(cd frontend && npm ci --include=dev --no-audit --no-fund && npm run build)

python manage.py collectstatic --noinput
