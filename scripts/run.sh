#!/usr/bin/env bash
# One-command boot for reviewers: creates the venv if missing, installs deps,
# applies migrations, seeds demo tenants, and starts the API.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q fastapi "uvicorn[standard]" sqlalchemy pydantic stripe apscheduler pytest httpx
fi

.venv/bin/python scripts/seed.py
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
