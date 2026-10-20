#!/usr/bin/env bash
# Format, lint and test the backend. Exits non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")/../backend"
.venv/bin/ruff format -q repopilot tests
.venv/bin/ruff check --fix -q repopilot tests || true
.venv/bin/ruff check repopilot tests
.venv/bin/python -m pytest -q -p no:cacheprovider "$@"
