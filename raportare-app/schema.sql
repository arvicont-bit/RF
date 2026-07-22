-- Schema scrisa in SQL standard (evitam sintaxa specifica SQLite acolo unde e posibil)
-- astfel incat migrarea ulterioara spre PostgreSQL sa fie directa.
-- Note pt migrare Postgres: INTEGER PRIMARY KEY -> SERIAL/BIGSERIAL, BLOB -> BYTEA,
-- TEXT (datetime) -> TIMESTAMP, INTEGER (bool 0/1) -> BOOLEAN.

CREATE TABLE IF NOT EXISTS tenants (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id),
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'admin',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- "firma client" - compania pentru care se proceseaza balante (Dial, SARCOM, Toto etc.)
CREATE TABLE IF NOT EXISTS client_companies (
  id INTEGER PRIMARY KEY,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id),
  name TEXT NOT NULL,
  cui TEXT,
  currency TEXT NOT NULL DEFAULT 'RON',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(tenant_id, name)
);

-- monetizare: un abonament per firma client
CREATE TABLE IF NOT EXISTS subscriptions (
  id INTEGER PRIMARY KEY,
  client_company_id INTEGER NOT NULL UNIQUE REFERENCES client_companies(id),
  plan TEXT NOT NULL DEFAULT 'trial',
  status TEXT NOT NULL DEFAULT 'active',
  price_amount INTEGER,
  currency TEXT NOT NULL DEFAULT 'RON',
  billing_cycle TEXT NOT NULL DEFAULT 'monthly',
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  current_period_end TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- planul de conturi universal + cod raportare (global, comun tuturor clientilor/tenantilor)
CREATE TABLE IF NOT EXISTS chart_accounts (
  id INTEGER PRIMARY KEY,
  clasa TEXT,
  cont TEXT NOT NULL UNIQUE,
  grad TEXT,
  denumire TEXT,
  tip TEXT NOT NULL,
  cod_mapare TEXT,
  descriere_cod TEXT,
  categorie TEXT,
  subcategorie TEXT,
  tratament_special TEXT,
  sursa TEXT
);

-- override de mapare per firma client, cand un cont analitic diverge de radacina standard
CREATE TABLE IF NOT EXISTS account_mapping_overrides (
  id INTEGER PRIMARY KEY,
  client_company_id INTEGER NOT NULL REFERENCES client_companies(id),
  cont TEXT NOT NULL,
  cod_mapare TEXT NOT NULL,
  descriere_cod TEXT,
  tratament_special TEXT,
  motivatie TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(client_company_id, cont)
);

-- fiecare balanta lunara incarcata, cu fisierul original atasat (blob) in baza de date
CREATE TABLE IF NOT EXISTS balance_uploads (
  id INTEGER PRIMARY KEY,
  client_company_id INTEGER NOT NULL REFERENCES client_companies(id),
  year INTEGER NOT NULL,
  month INTEGER NOT NULL,
  original_filename TEXT NOT NULL,
  file_blob BLOB NOT NULL,
  file_mimetype TEXT,
  uploaded_by INTEGER REFERENCES users(id),
  uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
  status TEXT NOT NULL DEFAULT 'pending',
  error_message TEXT,
  UNIQUE(client_company_id, year, month)
);

-- liniile brute, asa cum au fost parsate din fisierul incarcat
CREATE TABLE IF NOT EXISTS balance_lines (
  id INTEGER PRIMARY KEY,
  balance_upload_id INTEGER NOT NULL REFERENCES balance_uploads(id),
  cont TEXT NOT NULL,
  denumire TEXT,
  si_debit REAL DEFAULT 0,
  si_credit REAL DEFAULT 0,
  rulaj_luna_debit REAL DEFAULT 0,
  rulaj_luna_credit REAL DEFAULT 0,
  rulaj_cumulat_debit REAL DEFAULT 0,
  rulaj_cumulat_credit REAL DEFAULT 0,
  sf_debit REAL DEFAULT 0,
  sf_credit REAL DEFAULT 0
);

-- formatul universal: rezultatul dupa aplicarea motorului de mapare (Plan de conturi + reguli CONTRA/AUTO-INCHIS)
CREATE TABLE IF NOT EXISTS mapped_lines (
  id INTEGER PRIMARY KEY,
  balance_upload_id INTEGER NOT NULL REFERENCES balance_uploads(id),
  client_company_id INTEGER NOT NULL REFERENCES client_companies(id),
  year INTEGER NOT NULL,
  month INTEGER NOT NULL,
  cont TEXT NOT NULL,
  denumire TEXT,
  tip TEXT NOT NULL,
  cod_mapare TEXT,
  descriere_cod TEXT,
  tratament_special TEXT,
  diferenta_si REAL,
  diferenta_sf REAL,
  rulaj_cumulat_mapat REAL,
  rulaj_luna_mapat REAL,
  sursa_mapare TEXT,
  match_how TEXT
);

-- rezultatul verificarilor (egalitatile) per balanta incarcata
CREATE TABLE IF NOT EXISTS report_checks (
  id INTEGER PRIMARY KEY,
  balance_upload_id INTEGER NOT NULL UNIQUE REFERENCES balance_uploads(id),
  bs_check REAL,
  pl_cumulat REAL,
  pl_luna REAL,
  cont121_cumulat REAL,
  cont121_luna REAL,
  check_cumulat REAL,
  check_luna REAL,
  is_balanced INTEGER,
  computed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- snapshot agregat, in format universal (JSON), folosit de toate cele 3 tipuri de rapoarte
CREATE TABLE IF NOT EXISTS report_snapshots (
  id INTEGER PRIMARY KEY,
  client_company_id INTEGER NOT NULL REFERENCES client_companies(id),
  balance_upload_id INTEGER NOT NULL REFERENCES balance_uploads(id),
  year INTEGER NOT NULL,
  month INTEGER NOT NULL,
  data_json TEXT NOT NULL,
  generated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(client_company_id, year, month)
);

CREATE INDEX IF NOT EXISTS idx_client_companies_tenant ON client_companies(tenant_id);
CREATE INDEX IF NOT EXISTS idx_balance_uploads_client ON balance_uploads(client_company_id);
CREATE INDEX IF NOT EXISTS idx_mapped_lines_upload ON mapped_lines(balance_upload_id);
CREATE INDEX IF NOT EXISTS idx_balance_lines_upload ON balance_lines(balance_upload_id);
CREATE INDEX IF NOT EXISTS idx_report_snapshots_client ON report_snapshots(client_company_id, year, month);
