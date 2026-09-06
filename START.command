#!/bin/bash
set -e

cd "$(dirname "$0")"

clear
printf '\n==============================================\n'
printf ' DENNI POV - KONTROLA POJISTENI\n'
printf ' Automaticke spusteni pro macOS\n'
printf '==============================================\n\n'

PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
  osascript -e 'display dialog "Na tomto Macu nebyl nalezen Python 3." buttons {"OK"} default button "OK" with icon stop'
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Prvni spusteni: vytvarim Python prostredi..."
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate

STAMP_FILE=".venv/.requirements-installed"
if [ ! -f "$STAMP_FILE" ] || [ requirements.txt -nt "$STAMP_FILE" ]; then
  echo "Kontroluji a instaluji potrebne balicky..."
  python3 -m pip install --upgrade pip >/dev/null
  python3 -m pip install -r requirements.txt
  touch "$STAMP_FILE"
fi

export FREETDSCONF="$PWD/freetds.conf"
export TDSVER="7.2"
export PORT="5001"

# Pokud na portu 5001 bezi stara instance teto aplikace, ukoncime ji.
OLD_PID="$(lsof -ti tcp:5001 2>/dev/null || true)"
if [ -n "$OLD_PID" ]; then
  echo "Ukoncuji predchozi instanci na portu 5001..."
  kill $OLD_PID 2>/dev/null || true
  sleep 1
fi

# Prohlizec otevreme po rozbehnuti Flasku.
(
  sleep 2
  open "http://127.0.0.1:5001/"
) &

echo
printf 'Web se spousti na: http://127.0.0.1:5001/\n'
printf 'Toto okno nech otevrene po dobu behu aplikace.\n\n'

exec python3 app.py
