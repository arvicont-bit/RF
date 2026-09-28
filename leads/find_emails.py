"""Completeaza coloanele website/email din leads.csv.

Pentru fiecare firma:
  1. daca coloana 'website' e goala, ghiceste domenii din denumire
     (ex. "ALFA CONSTRUCT SRL" -> alfaconstruct.ro, alfa-construct.ro);
  2. accepta site-ul DOAR daca pagina contine CUI-ul firmei (obligatoriu
     legal pe site-urile firmelor romanesti) -> fara potriviri gresite;
  3. extrage email-urile din prima pagina si din paginile de contact,
     preferand adresele generice de firma (office@, contact@, financiar@...).

Se colecteaza doar adrese publicate chiar de firma pe site-ul propriu.
Exemplu:
  python3 find_emails.py --in leads.csv --out leads_email.csv --workers 16
"""
import argparse
import concurrent.futures as cf
import csv
import html
import re
import ssl
import unicodedata
import urllib.request

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CONTACT_PATHS = ("", "contact", "contact.html", "contact.php", "contact-us", "contacte", "despre-noi")
GENERIC_PREFIXES = ("financiar", "contabilitate", "office", "contact", "info", "director",
                    "management", "admin", "secretariat", "comercial", "sales", "vanzari")
IGNORED = ("example.", "sentry", "wixpress", "domain.", "@2x", ".png", ".jpg", ".webp", ".svg")
LEGAL_FORMS = r"\b(s\.?r\.?l\.?|s\.?a\.?|s\.?n\.?c\.?|s\.?c\.?s\.?|p\.?f\.?a\.?|i\.?i\.?|ifn|societate|comercial[aă]?)\b"

CTX = ssl.create_default_context()
HEADERS = {"User-Agent": "Mozilla/5.0 (lead-research; +contact via site)"}


def slug_candidates(name):
    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    base = re.sub(LEGAL_FORMS, " ", base)
    words = re.findall(r"[a-z0-9]+", base)
    if not words:
        return []
    joined, dashed = "".join(words), "-".join(words)
    cands = [joined, dashed, words[0]] if len(words) > 1 else [joined]
    domains = []
    for c in dict.fromkeys(cands):
        if len(c) >= 3:
            domains += [f"{c}.ro", f"{c}.com"]
    return domains


def fetch(url, timeout=8):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            if "text/html" not in r.headers.get("Content-Type", "text/html"):
                return ""
            return r.read(600_000).decode("utf-8", "replace")
    except Exception:
        return ""


def page_has_cui(text, cui):
    return re.search(rf"(?<!\d){cui}(?!\d)", text) is not None


def extract_emails(text):
    text = html.unescape(text).replace("[at]", "@").replace("(at)", "@")
    found = []
    for e in EMAIL_RE.findall(text):
        e = e.strip(".").lower()
        if not any(i in e for i in IGNORED) and e not in found:
            found.append(e)
    return found


def rank_email(email, domain):
    local, _, host = email.partition("@")
    score = 0
    if domain and host.endswith(domain.split("//")[-1].removeprefix("www.")):
        score += 10
    for i, p in enumerate(GENERIC_PREFIXES):
        if local.startswith(p):
            score += len(GENERIC_PREFIXES) - i
            break
    return -score


def resolve(row):
    cui = row["cui"]
    sites = [row["website"]] if row.get("website") else [f"https://{d}" for d in slug_candidates(row["denumire"])]
    for site in sites:
        site = site if site.startswith("http") else f"https://{site}"
        home = fetch(site) or fetch(site.replace("https://", "http://"))
        if not home:
            continue
        pages = [home] + [fetch(f"{site.rstrip('/')}/{p}") for p in CONTACT_PATHS[1:]]
        text = "\n".join(pages)
        # Site ghicit: il acceptam doar daca apare CUI-ul firmei.
        if not row.get("website") and not page_has_cui(text, cui):
            continue
        emails = extract_emails(text)
        emails.sort(key=lambda e: rank_email(e, site))
        return site, emails
    return row.get("website", ""), []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default="leads.csv")
    ap.add_argument("--out", default="leads_email.csv")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0, help="proceseaza doar primele N (dupa scor)")
    args = ap.parse_args()

    with open(args.inp, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    todo = rows[: args.limit] if args.limit else rows
    fields = list(rows[0].keys()) + ["emailuri_alternative"] if rows else []

    done = 0
    with cf.ThreadPoolExecutor(args.workers) as pool:
        for row, (site, emails) in zip(todo, pool.map(resolve, todo)):
            row["website"] = site
            row["email"] = emails[0] if emails else ""
            row["emailuri_alternative"] = "; ".join(emails[1:5])
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(todo)}")

    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    found = sum(1 for r in todo if r.get("email"))
    print(f"Email gasit pentru {found}/{len(todo)} firme -> {args.out}")


if __name__ == "__main__":
    main()
