# Technické údaje v kartě vozidla

Technické údaje slouží pouze k zobrazení. Porovnávání pojištění, filtry,
počty a rozhodování o správné pojistce se nemění.

- Agent předává samostatný úplný index `sql_technical` všech nesmazaných
  SQL vozidel, včetně vozidel mimo filtry POV. Klíčem je normalizované VIN.
- Pro duplicitní VIN se používá dosavadní výběr aktuální karty:
  nejnovější datum výkupu / výkupu z komise, při shodě nejvyšší OID.
  Technické údaje se připojují podle OID a nepřenášejí ze starší karty.
- Pokud VIN existuje v indexu SQL, obě karty používají SQL Vans Centre.
  Chybějící interní technické údaje se nepřepisují údaji Kostky.
- Datová kostka se automaticky načítá jen pro výsledkové VIN nepřítomné
  v úplném SQL indexu. Již uložená data PostgreSQL se používají dál.
  Zůstává limit 15 VIN na dávku, platnost cache 30 dní a zastavení při
  omezení poskytovatele. Otevření detailu může také spustit dávku na pozadí.
- U starých snapshotů lze zobrazit známé SQL základy. Pokud není přítomnost
  v SQL ověřena, zobrazí se čekání na následující pravidelnou kontrolu;
  samotné chybějící OID ve výsledku není důkaz nepřítomnosti v SQL.
  Pokud už jsou data Kostky uložená, zůstanou viditelná s upozorněním,
  že SQL zatím nebylo ověřeno; nové dotazy do Kostky se nespouští.
- Dosavadní ruční vyhledání libovolného VIN na samostatné kartě zůstává
  zachováno. Pokud je VIN v SQL indexu, i toto vyhledání použije SQL.

SQL rozšíření obsahuje pouze SELECT a nastavení lokálních proměnných.
Zůstává pod existující kontrolou `validate_read_only`. Nepovinné technické
sloupce se hledají jen podle explicitních názvů a vhodných datových typů.
Číselné cizí klíče barev/paliva/kategorie se nevydávají za popisy.
Nedostupný technický sloupec neblokuje kontrolu pojištění. Reálnou dostupnost
jednotlivých sloupců musí potvrdit první běh aktualizovaného agenta.

## Ověření

`python -m unittest test_vehicle_technical test_agent_authorization test_agent_schedule test_sync_resilience`

`node test_vehicle_technical.js` a `node test_followup_groups.js`

Nové testy ověřují prioritu SQL i pro filtrovaná vozidla, OID při duplicitě,
využití uložené Kostky, chybějící cache, výpadek úložiště, neplatné VIN,
autorizaci, staré snapshoty a zobrazení zdroje v obou kartách.

Celá původní sada na výchozím commitu 62d461f obsahuje 4 selhání a 3 chyby
(testy řízení MCP, staré očekávání dvojího pojištění, health bez PostgreSQL,
export XLSX). Stejné případy selhávají po změně. Samostatný původní JS test
průběhu XLSX také selhává na nezměněném výchozím commitu.
