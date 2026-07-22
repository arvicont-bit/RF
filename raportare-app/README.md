# Raportare Financiara — aplicatie web multi-client

Aplicatie care proceseaza balante de verificare lunare pentru mai multe firme
client, aplica automat Planul de Conturi + regulile SOP (conturi CONTRA,
conturi AUTO-INCHIS, cautare pe radacina de cont) si genereaza trei tipuri
de rapoarte per firma / luna / an:

1. **Raport 1** — P&L, Bilant, Capital de lucru (verificarile BS/P&L/#121/Check).
2. **Raport 2** — detaliat, structura de definit ulterior (toate datele mapate
   sunt deja disponibile, gata de reorganizat in orice format).
3. **Raport 3** — dashboard grafic (venituri/cheltuieli/profit in timp,
   structura bilantului).

## De ce Flask + SQLite (si nu Next.js + Postgres, cum era planul initial)

Mediul in care a fost construita aplicatia avea, la momentul dezvoltarii,
acces de retea blocat complet (npm/pip/apt indisponibile), deci nu s-a putut
instala Next.js/Prisma/driver Postgres. Am construit aplicatia 100% din ce
era deja disponibil local: Python + Flask + SQLite, **fara nicio dependenta
externa** (nici macar CDN pentru CSS/JS — stilizarea si graficele sunt scrise
de mana, in `static/style.css` si `static/charts.js`).

Aceasta e o baza solida si portabila: schema SQL (`schema.sql`) e scrisa
in SQL standard, fara sintaxa specifica SQLite, tocmai ca migrarea la
PostgreSQL sa fie directa (vezi mai jos).

## Arhitectura

```
raportare-app/
  main.py                 - aplicatia Flask (rute, autentificare, upload)
  main_runner.py           - script de pornire (init DB + app.run)
  schema.sql               - schema completa a bazei de date
  app/
    db.py                  - conexiune SQLite
    mapping_engine.py       - motorul de mapare (SOP: CONTRA, AUTO-INCHIS, radacina)
    balance_parser.py       - parser balante brute .xlsx (detectie automata coloane)
    processing.py           - pipeline: upload -> parsare -> mapare -> checks -> snapshot
    seed_chart_accounts.py  - populeaza planul de conturi din data/seed/*.xlsx
  templates/                - pagini HTML (Jinja2)
  static/
    style.css                - stilizare proprie (fara Tailwind CDN)
    charts.js                 - grafice SVG proprii (fara Chart.js CDN)
  data/
    seed/Plan de Conturi - Mapare Cod Raportare.xlsx   - planul de conturi (499 conturi)
    raportare.db             - baza de date SQLite (creata la prima rulare)
```

### Baza de date — ce contine

- `tenants` / `users` — contul de administrare (cabinetul contabil).
- `client_companies` — firmele client (Dial, SARCOM, Toto etc.), separate
  logic prin coloana `tenant_id` pe fiecare tabel relevant. Fiecare query
  filtreaza automat pe tenant, deci datele intre firme/tenanti nu se ating
  niciodata (testat explicit — vezi sectiunea de testare mai jos).
- `subscriptions` — abonamentul fiecarei firme client (monetizare per firma).
- `chart_accounts` — planul de conturi universal + cod de raportare (comun,
  seed din fisierul `.xlsx` deja validat).
- `account_mapping_overrides` — mapari specifice per firma, cand un cont
  analitic diverge de radacina standard (echivalentul conturilor "portocalii"
  din pachetele Excel anterioare).
- `balance_uploads` — **fisierul original incarcat este stocat direct in
  baza de date** (coloana `file_blob`), asa cum ati cerut, impreuna cu
  firma/luna/an.
- `balance_lines` — liniile brute parsate din fisierul incarcat.
- `mapped_lines` — formatul universal, dupa aplicarea motorului de mapare.
- `report_checks` — rezultatul verificarilor (egalitatile).
- `report_snapshots` — agregat JSON in format universal, folosit de toate
  cele 3 rapoarte, tinut per firma / luna / an.

## Rulare locala

```bash
pip install -r requirements.txt --break-system-packages   # sau intr-un venv
python3 app/seed_chart_accounts.py                         # populeaza planul de conturi
python3 main_runner.py                                     # porneste pe portul 5050
```

Deschideti `http://localhost:5050`, creati un cont (Inregistrare), adaugati
o firma client, incarcati o balanta `.xlsx`.

## Migrare la PostgreSQL (cand sunteti gata de productie)

1. Instalati `psycopg2-binary` si un ORM/driver dupa preferinta.
2. Rulati `schema.sql` pe Postgres — e scris in SQL standard; singurele
   ajustari sunt: `INTEGER PRIMARY KEY` → `SERIAL PRIMARY KEY`,
   `BLOB` → `BYTEA`, `datetime('now')` → `now()`.
3. Inlocuiti `app/db.py` cu o conexiune `psycopg2`/`asyncpg` — restul
   codului (`processing.py`, `mapping_engine.py`, rutele din `main.py`)
   foloseste doar SQL standard prin `conn.execute(...)`, deci schimbarile
   sunt minime, izolate in `db.py`.

## Deployment — cea mai rapida cale (5 minute)

**Railway** sau **Render** (ambele suporta Flask + volum persistent pentru
SQLite, sau Postgres gestionat direct din platforma):

1. Creati cont gratuit pe [railway.app](https://railway.app) sau
   [render.com](https://render.com).
2. Conectati acest cod (upload direct sau printr-un repo Git).
3. Railway/Render detecteaza `Dockerfile`-ul inclus si il ruleaza automat.
4. Setati variabila de mediu `APP_SECRET_KEY` la o valoare aleatorie/secreta.
5. Pentru persistenta datelor: fie atasati un volum persistent pentru
   `data/raportare.db` (SQLite), fie (recomandat pentru productie reala)
   migrati la Postgres gestionat de platforma, per sectiunea de mai sus.

**Alternativ, pe un VPS/server propriu:**

```bash
docker build -t raportare-app .
docker run -d -p 5050:5050 -v $(pwd)/data:/app/data --env APP_SECRET_KEY=... raportare-app
```

## Monetizare (Stripe-ready)

Tabelul `subscriptions` are deja coloanele `stripe_customer_id` /
`stripe_subscription_id` / `plan` / `status` / `billing_cycle`. Pagina
`/clients/<id>/subscription` permite schimbarea planului manual acum;
cand decideti modelul final de pricing, se adauga integrarea Stripe
(webhook-uri pentru `invoice.paid` / `subscription.updated`) fara sa fie
nevoie de nicio schimbare de schema.

## Ce s-a testat end-to-end

- Balanta reala **Toto SRL (Aprilie 2025)** incarcata prin aplicatie ->
  Check cumulat = **-0.01 lei**, Check luna = **0.00 lei** — identic cu
  pachetul Excel validat manual anterior.
- Balanta reala **SARCOM (Septembrie)** incarcata prin aplicatie -> BS
  check = 0 (structura corecta), Check cumulat reflecta acelasi neechilibru
  cunoscut si documentat separat (conturile 711/609/709, in asteptarea
  confirmarii contabilului) — aplicatia nu ascunde/forteaza artificial
  un rezultat echilibrat.
- Separare multi-tenant: un al doilea cont de administrare nu vede firmele
  primului cont, iar accesul direct pe URL la o firma din alt tenant
  intoarce 404.
- Fisierul original incarcat, descarcat inapoi din baza de date, e identic
  byte cu byte cu fisierul incarcat (verificat prin `md5sum`).

## Ce urmeaza (nu e inclus inca)

- Structura exacta a **Raportului 2** (detaliat) — placeholder functional,
  gata de umplut cand stabiliti formatul.
- Cash Flow (necesita minim doua perioade consecutive incarcate pentru
  aceeasi firma — schema il suporta, calculul propriu-zis ramane de scris
  cand exista date reale pe doua luni).
- Integrarea Stripe live (infrastructura e pregatita, lipsesc doar cheile
  si webhook-urile, dupa ce decideti pricingul).
- Ecran de mapare manuala pentru conturile nemapate (acum se raporteaza
  clar in UI, dar corectarea se face direct in baza de date / tabelul
  `account_mapping_overrides`; un formular dedicat e usor de adaugat).
