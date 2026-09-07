#!/bin/bash
set -e

cd "$(dirname "$0")"

clear
printf '\n==============================================\n'
printf ' DENNI POV - WEB\n'
printf ' Spusteni webove aplikace pro macOS\n'
printf '==============================================\n\n'

PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "❌ Python 3 nebyl nalezen."
  read -n 1 -s -r -p "Stiskni libovolnou klávesu pro zavření..."
  echo
  exit 1
fi

if [ ! -f "app.py" ]; then
  echo "❌ Vedle tohoto souboru chybí app.py."
  echo "Stáhni celý repozitář, ne jen START_WEB.command."
  read -n 1 -s -r -p "Stiskni libovolnou klávesu pro zavření..."
  echo
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "První spuštění: vytvářím Python prostředí..."
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate

STAMP_FILE=".venv/.requirements-installed"
if [ -f "requirements.txt" ]; then
  if [ ! -f "$STAMP_FILE" ] || [ requirements.txt -nt "$STAMP_FILE" ]; then
    echo "Kontroluji a instaluji potřebné balíčky..."
    python3 -m pip install --upgrade pip >/dev/null
    python3 -m pip install -r requirements.txt
    touch "$STAMP_FILE"
  fi
fi

export FREETDSCONF="$PWD/freetds.conf"
export TDSVER="7.2"
export PORT="5001"

OLD_PID="$(lsof -ti tcp:5001 2>/dev/null || true)"
if [ -n "$OLD_PID" ]; then
  echo "Ukončuji předchozí instanci na portu 5001..."
  kill $OLD_PID 2>/dev/null || true
  sleep 1
fi

(
  sleep 2
  open "http://127.0.0.1:5001/"
) &

echo
printf '✅ Web se spouští na: http://127.0.0.1:5001/\n'
printf '✅ Test zdraví: http://127.0.0.1:5001/health\n'
printf 'Toto okno nech otevřené po dobu běhu aplikace.\n\n'

exec python3 app.py
