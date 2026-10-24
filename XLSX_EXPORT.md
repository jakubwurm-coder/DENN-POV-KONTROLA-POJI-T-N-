# Export XLSX auditu

Příprava se spouští přihlášeným `POST /api/xlsx-export` (202), stav poskytuje
`GET /api/xlsx-export/<id>`. Soubor se stahuje z `/download/xlsx?job=<id>` až po
stavu `ready`. Původní odkaz `/download/xlsx` otevírá stejný grafický postup.

Export používá samostatný Python proces a sekvenční `openpyxl` zápis. Celý Excel
nevzniká v paměti webového požadavku. Status je malý atomicky nahrazovaný soubor;
čtení statusu nenačítá databázi. Hotový XLSX se přenáší přes `send_file`, včetně
Content-Length a podpory Range. Procenta přípravy = skutečně zapsané datové řádky /
celkový počet datových řádků všech listů. Komprese, počáteční načtení a čekání na
kancelářského agenta mají neurčitý indikátor. Procenta sítě vycházejí výhradně z
měřitelných událostí XHR; bez známé délky se ukazuje pouze počet přijatých bajtů.
Dokončení přenosu znamená převzetí souboru prohlížečem, nikoliv potvrzené uložení
na disk. Při chybě sítě lze zopakovat přenos stejného připraveného souboru.

Soubor i stav jsou v privátním dočasném adresáři a vyžadují původní přihlášenou
relaci. Exporty platí jednu hodinu; starší soubory se uklízejí při dalším spuštění
exportu. V jednu chvíli běží jeden export na instanci, opakovaný požadavek stejné
relace vrací jeho ID. Procesní zámek funguje i přes více vláken/pracovníků
Gunicornu. Konfigurace odpovídá současné jedné instanci Renderu (Linux).

Dočasné soubory nepřežijí nasazení ani restart celé instance. Web oznámí chybějící
či přerušený export a nabídne nový pokus. Pro více instancí nebo trvalou frontu
je nutné přejít na sdílené úložiště a samostatnou frontu. Tato změna žádné nové
placené služby nevyžaduje. Export nemá připojení do zdrojové SQL databáze ani
nemění pravidla kontroly, přihlášení nebo zpracování Uniqa/Allianz.

## Ověření

- `python -m unittest test_xlsx_export test_web_login test_agent_authorization test_agent_schedule test_dmsdata_csv test_sync_resilience`: 22 testů.
- `node test_xlsx_progress.js`: 5 scénářů včetně měřeného i neměřitelného přenosu,
  selhání sítě/opakování, vypršení přihlášení a čekání na agenta.
- Zátěžový test: 100 000 syntetických SQL řádků; po opětovném otevření XLSX
  potvrzeno všech 100 000 řádků. Lokálně zápis 24,8 s, soubor 4 779 595 bajtů,
  špičková paměť testovacího procesu 70 MB (včetně vstupních dat).
- Gunicorn s timeoutem 2 s: zadání 0,012 s, generování 4,91 s, 20 úspěšných
  kontrol stavu a zdraví během přípravy; žádný WORKER TIMEOUT.
- Lokální vizuální test v prohlížeči dokončil přípravu i skutečné stažení souboru.

Původní testy `test_control_api` mají dvě selhání oprávnění MCP a
`test_pov_decision_matrix` jedno selhání očekávání dvojího pojištění. Všechna tři
byla reprodukována také na nezměněném commitu f6577ba; export je nemění.

## Úplné porovnání SQL (verze 2, 24. 10. 2026)

Každá fyzická nesmazaná SQL karta má samostatný výsledek porovnání.
Zahrnuty jsou všechny stavy, historické prodeje bez časového omezení,
starší OID stejného VIN a karty bez VIN (výsledek nelze ověřit).
Na webu zůstává aktuální karta VIN; prodané bez pojištění a neutrální
karty mimo pravidla POV se skrývají. Excel používá samostatný úplný
seznam výsledků, nikoli webový seznam. Dvojí pojištění má přednost ve
všech stavech; rozeznává se také více různých aktivních ČPS UNIQA.

Export zachovává všechny načtené pojistné řádky UNIQA i Allianz.
Allianz zdroj obsahuje pouze identifikátory: neznámá čísla smluv a data
se nedoplňují odhadem. SQL audit uvádí zdroj SQL Vans Centre, OID,
pojistný výsledek a detail. Obohacení technických údajů nadále používá
stávající ověřenou integraci Datové kostky a prioritu úplného SQL indexu.

Server před uložením a vytvořením XLSX ověří verzi schématu, shodu
počtu řádků s SQL celkem, unikátnost OID a právě jeden výsledek pro
každý OID. Starý či neúplný audit odmítne. Uložené poznámky a řešení
se aplikují i na úplný export; pojistný výsledek zůstává samostatný.

Ověření: `python -m unittest test_complete_audit test_xlsx_export
 test_vehicle_technical test_agent_authorization test_agent_schedule
 test_sync_resilience`, `python test_pov_decision_matrix.py` a tři
JS testy průběhu XLSX, skupin případů a technických údajů.
Celá historická sada má nadále dvě dřívější selhání v očekávání
oprávnění MCP a jednu chybu health testu bez PostgreSQL. Odpovídající
produkční health se ověřuje proti skutečnému úložišti samostatně.
