# Spuštění kontroly přes API

Online aplikace používá pro webové tlačítko, REST API i MCP stejný handler.
Požadavek zpracovává stávající kancelářský Windows agent. TIRBazar zůstává pouze pro čtení.

## Konfigurace

Na Renderu nastavte nové náhodné tajné tokeny (alespoň 32 náhodných bajtů):

- `ASSISTANT_CONTROL_TOKEN`: REST spuštění a čtení stavu.
- `MCP_CONTROL_TOKEN`: MCP spuštění a čtení stavu.

Stávající `ASSISTANT_API_TOKEN` a `MCP_CAPABILITY_TOKEN` nadále nemohou spouštět kontrolu.
Bez nových tokenů je řídicí rozhraní vypnuté. Tokeny neukládejte do GitHubu ani klientského JavaScriptu.
Původní webové tlačítko funguje beze změny.

## REST

`POST /api/assistant/run` s hlavičkou `Authorization: Bearer <ASSISTANT_CONTROL_TOKEN>`.
Vrací `202` a `request_id`, `started_at`, `status: pending`. Jde o přijetí požadavku, nikoli hotový výsledek.
Při probíhající kontrole nebo jiném čekajícím příkazu vrací `409`; chybné oprávnění vrací `401`.

Stav načítejte přes `GET /api/assistant/status` se stejným tokenem.
Dokud `running=true`, souhrny nepovažujte za dokončený výsledek.
Dokončení ověřte přes `running=false`, nový `generated_at` a `error`.
`result_is_current` označuje dokončený snapshot; při chybě ještě vždy zkontrolujte `error` a `sources`.
`request_id` identifikuje odeslaný příkaz. Stavový endpoint vrací poslední globální snapshot,
nikoli archiv výsledků přiřazených jednotlivým request_id.

## MCP

Pro řídicí připojení použijte `/mcp/<MCP_CONTROL_TOKEN>`.
Seznam nástrojů obsahuje `start_insurance_check` bez argumentů.
Po jeho zavolání sledujte `get_insurance_status`. Stávající připojení s čtecím tokenem
nový nástroj nezobrazuje a nemůže jej zavolat. URL obsahuje tajný token; nesdílejte ji veřejně.
Připojení asistenta musí být aktualizováno samostatně, samotný deploy jeho oprávnění nezmění.

## Opakovaný test

Pro deset skutečných kontrol spouštějte další běh až po dokončení předchozího.
Tříminutový rozestup je možný jen pokud jednotlivé běhy skončí včas.
Nedostupný nebo pomalý Windows agent může zabránit dokončení všech deseti kontrol za půl hodiny.
