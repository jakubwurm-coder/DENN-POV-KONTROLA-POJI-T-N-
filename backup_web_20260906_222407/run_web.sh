#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ -d .venv ]; then
  source .venv/bin/activate
fi

export FREETDSCONF="${FREETDSCONF:-$PWD/freetds.conf}"
export TDSVER="${TDSVER:-7.2}"
export PORT="${PORT:-5000}"

python3 preflight.py || true
exec python3 app.py
