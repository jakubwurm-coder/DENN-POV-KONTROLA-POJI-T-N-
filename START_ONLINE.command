#!/bin/bash
set -e

cd "$(dirname "$0")"

clear
printf '\n==============================================\n'
printf ' DENNI POV - ONLINE / macOS\n'
printf ' Kancelarsky agent pro Render\n'
printf '==============================================\n\n'

if [ -d ".git" ] && command -v git >/dev/null 2>&1; then
  echo "Kontroluji nejnovější verzi z GitHubu..."
  git pull --ff-only origin main || true
  echo
fi

PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "❌ Python 3 nebyl nalezen."
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
export DENNI_POV_CLOUD_URL="https://denni-pov-kontrola.onrender.com"

(
  sleep 2
  open "$DENNI_POV_CLOUD_URL"
) &

echo
printf '✅ Online web: %s\n' "$DENNI_POV_CLOUD_URL"
printf '✅ Agent bude automaticky kontrolovat data a poslouchat požadavky z webu.\n'
printf 'Toto okno nech otevřené, aby šla kontrola spustit i vzdáleně.\n\n'

exec python3 cloud_agent.py
