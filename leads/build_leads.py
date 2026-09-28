"""Construieste lista de lead-uri (firme din Bucuresti, Ilfov, Prahova cu
cifra de afaceri peste un prag in EUR) din datele deschise ale Ministerului
Finantelor publicate pe data.gov.ro.

Surse (descarcare manuala, gratuita):
  1. "Situatiile financiare 2024" (si optional 2023, pentru crestere):
     https://data.gov.ro/dataset/situatii_financiare_2024
     -> fisierele WEB_*.txt (date) + WEB_*.csv (specificatia coloanelor),
        puse toate in acelasi folder.
  2. "Date de identificare platitori" (structurat pe judete):
     https://data.gov.ro/organization/mfp  (cel mai recent set)
     -> fisierele pentru BUCURESTI, ILFOV, PRAHOVA.

Exemplu:
  python3 build_leads.py --fin-dir date/sf2024 --fin-prev-dir date/sf2023 \
      --id-file date/id/BUCURESTI.csv --id-file date/id/ILFOV.csv \
      --id-file date/id/PRAHOVA.csv --out leads.csv

Fara dependente externe (doar biblioteca standard Python).
"""
import argparse
import csv
import glob
import os
import re
import sys
import unicodedata

TARGET_COUNTIES = ("BUCURESTI", "ILFOV", "PRAHOVA")

# Ordinea implicita a indicatorilor din fisierele WEB_BL_BS_SL / WEB_UU
# (folosita doar daca fisierul .csv de specificatie lipseste).
DEFAULT_INDICATORS = [
    "active imobilizate", "active circulante", "stocuri", "creante",
    "casa si conturi la banci", "cheltuieli in avans", "datorii",
    "venituri in avans", "provizioane", "capitaluri total",
    "capital subscris varsat", "patrimoniul regiei", "cifra de afaceri neta",
    "venituri totale", "cheltuieli totale", "profit brut", "pierdere bruta",
    "profit net", "pierdere neta", "numar mediu de salariati",
]

# Cuvinte-cheie -> camp intern. Primul match castiga.
FIN_FIELDS = [
    ("cui", ("cui", "cod fiscal", "cod_fiscal")),
    ("caen", ("caen",)),
    ("ca", ("cifra de afaceri",)),
    ("venituri", ("venituri totale",)),
    ("cheltuieli", ("cheltuieli totale",)),
    ("profit_net", ("profit net",)),
    ("pierdere_neta", ("pierdere neta",)),
    ("datorii", ("datorii",)),
    ("capitaluri", ("capitaluri total", "capitaluri - total", "capitaluri proprii")),
    ("active_imob", ("active imobilizate",)),
    ("active_circ", ("active circulante",)),
    ("creante", ("creante",)),
    ("stocuri", ("stocuri",)),
    ("salariati", ("salariati",)),
]

ID_FIELDS = [
    ("cui", ("cui", "cod fiscal", "cod_fiscal", "cif")),
    ("denumire", ("denumire", "nume")),
    ("judet", ("judet",)),
    ("localitate", ("localitate", "oras", "sector")),
    ("adresa", ("adresa", "strada")),
    ("telefon", ("telefon",)),
    ("stare", ("stare", "status")),
]

# Sectoare cu contabilitate complexa / nevoie mare de analiza financiara.
CAEN_PRIORITY = {
    "41": "constructii", "42": "constructii", "43": "constructii",
    "46": "comert en-gros", "45": "auto", "47": "retail",
    "49": "transport", "52": "logistica", "68": "imobiliare",
    "62": "IT", "71": "inginerie", "55": "HoReCa", "56": "HoReCa",
    "86": "sanatate", "10": "productie alimentara", "22": "productie",
    "25": "productie metal", "28": "productie utilaje", "33": "service industrial",
}
# Excluse: competitori (6920), finante/asigurari, administratie publica.
CAEN_EXCLUDE_PREFIX = ("6920", "64", "65", "66", "84", "94", "99")


def norm(text):
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip().lower()


def read_text(path):
    for enc in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Nu pot decoda {path}")


def sniff_delimiter(line):
    counts = {d: line.count(d) for d in ("^", ";", "|", "\t", ",")}
    return max(counts, key=counts.get)


def parse_number(value):
    value = (value or "").strip().replace(" ", "")
    if not value:
        return 0.0
    if "," in value and "." not in value:
        value = value.replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return 0.0


def clean_cui(value):
    digits = re.sub(r"\D", "", value or "")
    return digits.lstrip("0")


def map_columns(headers, fields):
    """Intoarce {camp_intern: index_coloana} pe baza cuvintelor-cheie."""
    mapping = {}
    normalized = [norm(h) for h in headers]
    for field, keywords in fields:
        for idx, header in enumerate(normalized):
            if idx in mapping.values():
                continue
            if any(k == header or k in header for k in keywords):
                mapping[field] = idx
                break
    return mapping


def spec_headers(spec_path):
    """Citeste .csv-ul de specificatie; intoarce lista de denumiri coloane."""
    text = read_text(spec_path).strip().splitlines()
    if not text:
        return None
    delim = sniff_delimiter(text[0])
    rows = [r for r in csv.reader(text, delimiter=delim) if any(c.strip() for c in r)]
    if len(rows) == 1 or len(rows[0]) > 3:
        # Specificatie pe un singur rand (antet).
        return [c.strip() for c in rows[0]]
    # Specificatie pe verticala: "I1;Active imobilizate" etc. -> ia ultima coloana text.
    headers = []
    for r in rows:
        label = next((c for c in reversed(r) if re.search(r"[a-zA-Z]{3}", c)), r[0])
        headers.append(label.strip())
    if headers and norm(headers[0]) in ("denumire", "coloana", "indicator", "camp"):
        headers = headers[1:]
    return headers


def load_financials(fin_dir):
    """Citeste toate WEB_*.txt din folder -> {cui: dict indicatori}."""
    result = {}
    files = sorted(glob.glob(os.path.join(fin_dir, "*.txt")))
    if not files:
        sys.exit(f"Nu am gasit fisiere .txt in {fin_dir}")
    for txt in files:
        lines = read_text(txt).splitlines()
        if not lines:
            continue
        delim = sniff_delimiter(lines[0])
        first = [c.strip() for c in lines[0].split(delim)]
        has_header = not clean_cui(first[0])
        spec = os.path.splitext(txt)[0] + ".csv"
        if has_header:
            headers = first
        elif os.path.exists(spec):
            headers = spec_headers(spec)
        else:
            headers = ["CUI", "CAEN"] + DEFAULT_INDICATORS
        mapping = map_columns(headers, FIN_FIELDS)
        if "cui" not in mapping:
            mapping["cui"] = 0
        if "ca" not in mapping:
            print(f"  ! {os.path.basename(txt)}: fara coloana 'cifra de afaceri', ignorat")
            continue
        n = 0
        for line in lines[1 if has_header else 0:]:
            cells = line.split(delim)
            if len(cells) <= mapping["ca"]:
                continue
            cui = clean_cui(cells[mapping["cui"]])
            if not cui:
                continue
            rec = {"sursa": os.path.basename(txt)}
            for field, idx in mapping.items():
                if field == "cui" or idx >= len(cells):
                    continue
                rec[field] = cells[idx].strip() if field == "caen" else parse_number(cells[idx])
            # Pastreaza inregistrarea cu CA maxima daca un CUI apare in mai multe fisiere.
            if cui not in result or rec.get("ca", 0) > result[cui].get("ca", 0):
                result[cui] = rec
            n += 1
        print(f"  {os.path.basename(txt)}: {n} firme")
    return result


def load_identification(paths):
    """Citeste fisierele de identificare -> {cui: dict}; doar judetele tinta."""
    result = {}
    for path in paths:
        lines = read_text(path).splitlines()
        if not lines:
            continue
        delim = sniff_delimiter(lines[0])
        reader = csv.reader(lines, delimiter=delim)
        headers = next(reader)
        mapping = map_columns(headers, ID_FIELDS)
        if "cui" not in mapping:
            sys.exit(f"{path}: nu gasesc coloana CUI in antet {headers}")
        county_from_name = norm(os.path.basename(path)).upper()
        n = 0
        for row in reader:
            get = lambda f: row[mapping[f]].strip() if f in mapping and mapping[f] < len(row) else ""
            cui = clean_cui(get("cui"))
            if not cui:
                continue
            judet = norm(get("judet")).upper() or county_from_name
            judet = "BUCURESTI" if "BUCURESTI" in judet or "SECTOR" in judet else judet
            if not any(c in judet for c in TARGET_COUNTIES):
                continue
            stare = norm(get("stare"))
            if any(s in stare for s in ("radiat", "inactiv", "dizolv", "lichid", "faliment", "insolv")):
                continue
            result[cui] = {
                "denumire": get("denumire"),
                "judet": next(c for c in TARGET_COUNTIES if c in judet),
                "localitate": get("localitate"),
                "adresa": get("adresa"),
                "telefon": get("telefon"),
            }
            n += 1
        print(f"  {os.path.basename(path)}: {n} firme active in judetele tinta")
    return result


def score_lead(fin, prev, eur_rate):
    """Scor 0-100 + motivele care fac lead-ul 'transformabil'."""
    score, reasons = 0, []
    ca_eur = fin.get("ca", 0) / eur_rate
    salariati = fin.get("salariati", 0)
    venituri = fin.get("venituri", 0)
    profit = fin.get("profit_net", 0) - fin.get("pierdere_neta", 0)
    active = fin.get("active_imob", 0) + fin.get("active_circ", 0)
    datorii = fin.get("datorii", 0)
    capitaluri = fin.get("capitaluri", 0)

    if 500_000 <= ca_eur <= 10_000_000:
        score += 20
        reasons.append("CA in zona tinta (0.5-10M EUR)")
    elif ca_eur > 10_000_000:
        score += 8
        reasons.append("CA mare (probabil departament financiar intern)")

    if 10 <= salariati <= 150:
        score += 15
        reasons.append(f"{int(salariati)} salariati (salarizare/HR complex)")
    elif 0 < salariati < 10:
        score += 5

    if prev and prev.get("ca", 0) > 0:
        growth = fin.get("ca", 0) / prev["ca"] - 1
        if growth >= 0.2:
            score += 15
            reasons.append(f"crestere CA {growth:+.0%} (depaseste capacitatea contabilului actual)")
        elif growth <= -0.15:
            score += 10
            reasons.append(f"scadere CA {growth:+.0%} (nevoie de analiza/restructurare)")

    if venituri > 0:
        margin = profit / venituri
        if margin < 0:
            score += 15
            reasons.append("pierdere neta (nevoie de analiza cost/profitabilitate)")
        elif margin < 0.03:
            score += 10
            reasons.append(f"marja neta mica {margin:.1%}")

    if capitaluri < 0:
        score += 15
        reasons.append("capitaluri proprii negative (risc art. 153^24 L31/1990)")

    if active > 0 and datorii / active > 0.7:
        score += 10
        reasons.append(f"indatorare ridicata {datorii / active:.0%} din active (raportari catre banci)")

    if active > 0 and fin.get("creante", 0) / active > 0.4:
        score += 5
        reasons.append("creante mari (nevoie de control cash-flow)")

    # Praguri de audit statutar (OMFP 1802/2014): 2 din 3 criterii.
    audit_hits = sum([
        active / eur_rate > 4_000_000,
        ca_eur > 8_000_000,
        salariati > 50,
    ])
    if audit_hits >= 2:
        score += 5
        reasons.append("depaseste pragurile de audit statutar")

    caen = (fin.get("caen") or "").strip()
    sector = CAEN_PRIORITY.get(caen[:2])
    if sector:
        score += 10
        reasons.append(f"sector {sector} (contabilitate complexa)")

    return min(score, 100), reasons


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fin-dir", required=True, help="folder cu WEB_*.txt + WEB_*.csv (anul curent)")
    ap.add_argument("--fin-prev-dir", help="folder cu situatiile anului anterior (pentru crestere)")
    ap.add_argument("--id-file", action="append", required=True, help="fisier de identificare pe judet (repetabil)")
    ap.add_argument("--eur-rate", type=float, default=4.97, help="curs RON/EUR (implicit 4.97)")
    ap.add_argument("--min-ca-eur", type=float, default=500_000)
    ap.add_argument("--min-score", type=int, default=0)
    ap.add_argument("--out", default="leads.csv")
    args = ap.parse_args()

    print("Citesc situatiile financiare...")
    fin = load_financials(args.fin_dir)
    prev = {}
    if args.fin_prev_dir:
        print("Citesc situatiile financiare ale anului anterior...")
        prev = load_financials(args.fin_prev_dir)
    print("Citesc datele de identificare...")
    ident = load_identification(args.id_file)

    min_ca_ron = args.min_ca_eur * args.eur_rate
    leads = []
    for cui, info in ident.items():
        f = fin.get(cui)
        if not f or f.get("ca", 0) < min_ca_ron:
            continue
        caen = (f.get("caen") or "").strip()
        if caen.startswith(CAEN_EXCLUDE_PREFIX):
            continue
        score, reasons = score_lead(f, prev.get(cui), args.eur_rate)
        if score < args.min_score:
            continue
        profit = f.get("profit_net", 0) - f.get("pierdere_neta", 0)
        leads.append({
            "scor": score,
            "cui": cui,
            "denumire": info["denumire"],
            "judet": info["judet"],
            "localitate": info["localitate"],
            "adresa": info["adresa"],
            "telefon": info["telefon"],
            "caen": caen,
            "cifra_afaceri_ron": round(f.get("ca", 0)),
            "cifra_afaceri_eur": round(f.get("ca", 0) / args.eur_rate),
            "cifra_afaceri_an_anterior_ron": round(prev.get(cui, {}).get("ca", 0)),
            "profit_net_ron": round(profit),
            "salariati": int(f.get("salariati", 0)),
            "motive": "; ".join(reasons),
            "website": "",
            "email": "",
        })

    leads.sort(key=lambda r: (-r["scor"], -r["cifra_afaceri_ron"]))
    fields = list(leads[0].keys()) if leads else ["scor", "cui", "denumire"]
    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(leads)
    by_county = {c: sum(1 for l in leads if l["judet"] == c) for c in TARGET_COUNTIES}
    print(f"\n{len(leads)} lead-uri scrise in {args.out}: {by_county}")


if __name__ == "__main__":
    main()
