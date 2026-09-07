#!/bin/zsh

HOST="${TIRBAZAR_SERVER:-192.168.1.100}"
PORT="${TIRBAZAR_PORT:-1433}"
DB="${TIRBAZAR_DATABASE:-TIRBazar}"
USER="${TIRBAZAR_USER:-TB}"
SERVICE="UNIQA_CHECKER_TIRBAZAR"
ACCOUNT="TB"
TSQL="/opt/homebrew/bin/tsql"

pause_exit() {
  echo
  read -k 1 "?Stiskni libovolnou klávesu pro zavření..."
  echo
}

echo "============================================"
echo " TEST SQL SERVERU V2 - TIRBazar"
echo "============================================"
echo "Server:   $HOST:$PORT"
echo "Databáze: $DB"
echo "Uživatel: $USER"
echo

if ! nc -z -w 3 "$HOST" "$PORT" >/dev/null 2>&1; then
  echo "❌ SQL server není dostupný na $HOST:$PORT"
  echo "Zkontroluj, že jsi ve stejné síti/VPN a že SQL Server běží."
  pause_exit
  exit 1
fi

echo "✅ Port $PORT je dostupný."

if [ ! -x "$TSQL" ]; then
  echo "❌ Chybí FreeTDS tsql: $TSQL"
  echo "Nainstaluj FreeTDS přes Homebrew a spusť test znovu."
  pause_exit
  exit 1
fi

PASSWORD=$(/usr/bin/security find-generic-password -a "$ACCOUNT" -s "$SERVICE" -w 2>/dev/null)
if [ -z "$PASSWORD" ]; then
  echo "❌ Heslo SQL nebylo nalezeno v macOS Klíčence."
  echo "Service: $SERVICE, account: $ACCOUNT"
  pause_exit
  exit 1
fi

TMP_CONF=$(mktemp -t test_sql_freetds.XXXXXX)
cat > "$TMP_CONF" <<EOF
[global]
    client charset = UTF-8
    encryption = off

[tirbazar]
    host = $HOST
    port = $PORT
    tds version = 7.2
    client charset = UTF-8
    encryption = off
EOF

export FREETDSCONF="$TMP_CONF"
export TDSVER="7.2"

cleanup() {
  PASSWORD=""
  rm -f "$TMP_CONF" >/dev/null 2>&1
}
trap cleanup EXIT

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
  pause_exit
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
pause_exit
