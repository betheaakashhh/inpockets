#!/usr/bin/env sh
# Scan the pinned runtime environment for known vulnerabilities (run in CI).
# Usage: scripts/audit_dependencies.sh   (needs network access to the advisory DB)
set -eu
pip freeze --exclude-editable | grep -E '^[A-Za-z0-9_.-]+==' > /tmp/requirements-audit.txt
pip-audit --no-deps --disable-pip -r /tmp/requirements-audit.txt
