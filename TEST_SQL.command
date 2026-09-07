#!/bin/zsh

cd "$(dirname "$0")" || exit 1

HOST="${TIRBAZAR_SERVER:-192.168.1.100}"
PORT="${TIRBAZAR_PORT:-1433}"
DB="${TIRBAZAR_DATABASE:-TIRBazar}"
USER="${TIRBAZAR_USER:-TB}"
SERVICE="UNIQA_CHECKER_TIRBAZAR"
ACCOUNT="TB"
TSQL="/opt/homebrew/bin/tsql"
FREETDS_CONF="$PWD/freetds.conf"

echo "============================================"
echo " TEST SQL SERVERU - TIRBazar"
echo "============================================"
echo "Server:   $HOST:$PORT"
echo "Databáze: $DB"
echo "Uživatel: $USER"
echo

if ! nc -z -w 3 "$HOST" "$PORT" >/dev/null 2>&1; then
  echo "❌ SQL server není dostupný na $HOST:$PORT"
  echo "Zkontroluj, že jsi ve stejné síti/VPN a že SQL Server běží."
  echo
  read -k 1 "?Stiskni libovolnou klávesu pro zavření..."
  echo
  exit 1
fi

echo "✅ Port $PORT je dostupný."

if [ ! -x "$TSQL" ]; then
  echo "❌ Chybí FreeTDS tsql: $TSQL"
  echo "Projekt ho používá pro připojení k SQL Serveru."
  echo
  read -k 1 "?Stiskni libovolnou klávesu pro zavření..."
  echo
  exit 1
fi

if [ ! -f "$FREETDS_CONF" ]; then
  echo "❌ Chybí $FREETDS_CONF"
  echo
  read -k 1 "?Stiskni libovolnou klávesu pro zavření..."
  echo
  exit 1
fi

PASSWORD=$(/usr/bin/security find-generic-password -a "$ACCOUNT" -s "$SERVICE" -w 2>/dev/null)
if [ -z "$PASSWORD" ]; then
  echo "❌ Heslo SQL nebylo nalezeno v macOS Klíčence."
  echo "Service: $SERVICE, account: $ACCOUNT"
  echo
  read -k 1 "?Stiskni libovolnou klávesu pro zavření..."
  echo
  exit 1
fi

export FREETDSCONF="$FREETDS_CONF"
export TDSVER="7.2"

SQL=$(cat <<EOF
USE [$DB]
GO
SET NOCOUNT ON
GO
SELECT '__SQL_TEST_OK__|' + CAST(@@SPID AS VARCHAR(20)) + '|' + DB_NAME()
GO
SELECT TOP 1 '__VOZIDLO_OK__|' + CAST(OID AS VARCHAR(20)) FROM dbo.Vozidlo WHERE GCRecord IS NULL ORDER BY OID
GO
exit
EOF
)

OUTPUT=$(printf "%s\n" "$SQL" | "$TSQL" -S tirbazar -U "$USER" -P "$PASSWORD" 2>&1)
STATUS=$?
PASSWORD=""

if [ $STATUS -ne 0 ]; then
  echo "❌ Přihlášení nebo SQL dotaz selhal."
  echo
  echo "$OUTPUT"
  echo
  read -k 1 "?Stiskni libovolnou klávesu pro zavření..."
  echo
  exit $STATUS
fi

if echo "$OUTPUT" | grep -q "__SQL_TEST_OK__"; then
  echo "✅ Přihlášení k SQL Serveru funguje."
else
  echo "⚠️ Spojení proběhlo, ale potvrzovací SQL výstup nebyl nalezen."
fi

if echo "$OUTPUT" | grep -q "__VOZIDLO_OK__"; then
  echo "✅ Databáze TIRBazar a tabulka dbo.Vozidlo jsou čitelné."
else
  echo "⚠️ Nepodařilo se potvrdit čtení z dbo.Vozidlo."
fi

echo
echo "Hotovo. Test pouze ČTE data, nic v databázi nemění."
echo
read -k 1 "?Stiskni libovolnou klávesu pro zavření..."
echo
