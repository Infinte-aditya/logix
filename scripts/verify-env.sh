#!/usr/bin/env bash
# Verifies local dev prerequisites. Prints OK/MISSING per tool.
# Exits 1 if anything is missing.
set -u

missing=0

check() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "OK      ${name}"
  else
    echo "MISSING ${name}"
    missing=1
  fi
}

check "git" command -v git
check "docker" docker --version
check "docker compose" docker compose version
check "python3.11" python3.11 --version
check "node 20" bash -c 'command -v node && node --version | grep -qE "^v20\."'

exit "${missing}"
