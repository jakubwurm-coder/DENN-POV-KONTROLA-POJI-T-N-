# Osobní přihlášení

Render proměnná `DENNI_POV_WEB_USERS` obsahuje JSON mapu e-mailů na scrypt hashe
hesel. Její hodnotu spravovat přímo v nastavení služby, nikdy ji neukládat do Gitu.
Pro přihlášení se e-mail ořízne a převede na malá písmena; heslo se nemění.

Při existenci této proměnné se původní společné přihlášení vypne. Prázdná nebo
chybná konfigurace nepovolí návrat na společné heslo. Hesla jednotlivých účtů
se ověřují pomocí Werkzeug; neexistující účet vrátí stejnou chybu jako špatné heslo.

Přihlášený e-mail je vidět v záhlaví. Ruční změny používají tuto ověřenou identitu
v auditní historii; jméno autora dodané klientem se ignoruje. Původní historii
ani staré neznámé autory novým osobám zpětně nepřidělovat.

Relace obsahuje otisk identity a aktuálního hashe. Odebrání účtu nebo změna jeho
hesla zneplatní jeho existující relace. Změna jiného účtu ostatní neodhlásí.
Při přechodu na osobní účty se také odmítnou staré relace společného účtu.
Agent VCSERVER a jeho vlastní autorizace zůstávají oddělené.

Všechny čtyři osobní účty mají stejná oprávnění k aplikaci jako dosavadní webový
účet. Přihlašovací údaje byly vygenerované mimo repozitář do soukromého místního
souboru s oprávněním pouze pro vlastníka. Render dostává pouze hashe.

Pro změnu hesla vygenerovat nové silné heslo a scrypt hash, změnit pouze příslušnou
položku JSON v Render proměnné a nasadit aktualizovanou konfiguraci. Zachovat
ostatní položky i nesouvisející proměnné služby. Samoobslužná změna hesla ani
odesílání přihlašovacích údajů e-mailem nejsou součástí této změny.

Ověření: `python -m unittest test_personal_accounts test_web_login`.
