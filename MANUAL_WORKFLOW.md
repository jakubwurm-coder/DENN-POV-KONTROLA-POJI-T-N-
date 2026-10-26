# Ruční workflow vozidel — 25. 10. 2026

Automatický výsledek (`status_raw`, `status`) se nemění ručním rozhodnutím.
Ruční stav se ukládá samostatně pro VIN, případně původní klíč SPZ.

| Ruční stav | Zobrazení | Nové červené problémy |
| --- | --- | --- |
| prázdný | Aktuální automatický problém červeně | ano, jen pokud stále trvá |
| K DOŘEŠENÍ | oranžově | ne |
| RUČNĚ OK | zeleně, včetně účtu a času potvrzení | ne |
| VYŘEŠENO (historická hodnota) | oranžové K DOŘEŠENÍ | ne |
| V POŘÁDKU (historická hodnota) | zelené RUČNĚ OK; neznámý původní autor | ne |

Starší VYŘEŠENO se nepřepisuje hromadnou migrací a neznamená zelené potvrzení.
U starých zásahů bez zaznamenané identity se zobrazuje „autor nezaznamenán“.

## Persistence a audit

- PostgreSQL tabulka `denni_pov_annotations` je autoritativní úložiště.
- `workflow_updated_by` a `workflow_updated_at` popisují ruční rozhodnutí.
  `updated_by` a `updated_at` popisují poslední úpravu poznámky nebo stavu.
  Úprava poznámky nepřepisuje autora ani čas potvrzení.
- Autor pochází z ověřené přihlašovací session; parametr autora v JSON se ignoruje.
  Starší session bez identity musí provést nové přihlášení.
- Osobní účty a jejich identita jsou popsány v `PERSONAL_ACCOUNTS.md`.
- Historie obsahuje starý a nový stav, poznámky, aktuální automatický výsledek,
  autora a čas. Zápis anotace a historie je jedna transakce. Souběžné první
  zápisy pro stejný klíč serializuje databázový zámek.
- Prázdná anotace po návratu na původní stav zůstává uložená, aby import staré
  mezipaměti neobnovil zrušené ruční rozhodnutí.
- Od 26. 10. 2026 aktuální přehled vždy určuje poslední automatický výsledek.
  Historický problém nikdy nezmění aktuální OK na červený případ. Dřívější nálezy
  zůstávají v historii běhů; v aktuálním přehledu ani Excelu se neopakují.
- Ruční rozhodnutí přetrvá další kontrolu pouze u stejného trvajícího problému.
  Po jeho odstranění, změně typu problému nebo zmizení vozidla z úplných výsledků
  se stav automaticky uzavře se systémovým záznamem v auditu. Poznámka zůstává.
  Pokud se problém vrátí, je nový a nepřevezme dřívější ruční schválení.
- Automatické uzavření se provádí výhradně po úspěšné dokončené kontrole.
  Průběžné a chybové synchronizace žádné ruční rozhodnutí neuzavírají.
- Historické sloupce `automatic_problem_status` a `automatic_problem_at` se nemažou.
  První z nich slouží jako vazba ručního rozhodnutí k příslušnému typu problému;
  není zdrojem aktuálního verdiktu ani důvodem k zobrazení červeného případu.
- Přehledy, API, Windows indikace a upozornění rozlišují obě ruční rozhodnutí.
  Excel obsahuje aktuální automatický výsledek a oddělený platný ruční stav, účet a čas.
- Objektivní počet skutečně pojištěných vozidel se ručním OK nezvyšuje.

## Migrace a nasazení

Inicializace schématu pouze přidává pět textových sloupců do anotací a sloupec
`changed_by` do historie pomocí `ADD COLUMN IF NOT EXISTS`. Žádné existující
záznamy ani tabulky nemaže a historickým zásahům nepřiděluje smyšlené autory.
Rozšíření proběhne při prvním přístupu k databázi po restartu nového kódu.

Nasazení na existující službu Render bylo uživatelem schváleno 26. 10. 2026.
Výchozí ostrý commit je `ebe15d8`; nasazuje se aktualizace hlavní větve.
Konektor Render nedokázal číst produkční databázi, protože databáze má prázdný
seznam povolených externích IP. Síťová pravidla zůstala beze změny. Produkční
schéma proto nebylo ověřeno přímým dotazem; migrace byla ověřena na samostatné
místní databázi PostgreSQL 16 a na původním schématu z repozitáře.

Nasadit backend a statické soubory společně; na Windows doručit i nový modul
`vehicle_workflow.py` a upravené moduly spotřebovávající stav. Lokální přeposílání
anotací nesmí předstírat identitu uživatele: bez přihlášení na centrálním serveru
se zápis odmítne. Ruční rozhodování bylo ověřeno v přihlášeném online UI.

## Ověření

Před nasazením 26. 10. 2026 prošlo 48 Python testů, 25 rozhodovacích scénářů
a všechny tři JavaScript sady.
`test_manual_workflow.py` testuje skutečné transakce v novém náhodném PostgreSQL
schématu. Po testu smaže pouze toto vlastní schéma. Připojení nastavuje výhradně
`POV_TEST_DATABASE_URL`; nepoužívat produkční databázi.

```sh
POV_TEST_DATABASE_URL="$LOCAL_TEST_DATABASE_URL" python -m unittest \
  test_manual_workflow test_xlsx_export test_sync_resilience \
  test_agent_authorization test_dmsdata_csv -v
node test_followup_groups.js
node test_vehicle_technical.js
node test_xlsx_progress.js
```

Testy pokrývají migraci, historická data, všechny problémové výsledky, změny stavů,
autora ze session, odmítnutí podvržené identity, chybu persistence, rollback při
chybě historie, souběžné zápisy, restart, skutečnou synchronizaci nového běhu,
odstranění starého nálezu po aktuálním OK a automatické uzavření ručního řešení a potlačení upozornění u převzatých
či potvrzených případů.

V širší původní sadě byly stejné tři chyby i na nezměněném commitu `ebe15d8`:
dva testy oprávnění MCP v `test_control_api` a test `/health` bez nakonfigurované
databáze v `test_web_login`. Tato úprava tyto nesouvisející chyby nemění.

Prohlížečový test na fiktivních vozidlech ověřil uložení RUČNĚ OK, přesun z nových
problémů do zeleného přehledu, autora a čas, návrat na původní stav se zachováním
poznámky a barevné odlišení všech tří stavů. Produkční vozidla nebyla měněna.
