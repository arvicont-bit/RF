# Lead-uri pentru cabinetul de contabilitate — București, Ilfov, Prahova

Construiește o listă de firme cu cifra de afaceri peste 500.000 EUR, le dă un scor
după cât de probabil e să aibă nevoie de contabilitate sau analiză financiară
și le caută email-urile publicate pe site-ul propriu.

Folosește doar Python din biblioteca standard.

## 1. Datele (gratuite, oficiale — Ministerul Finanțelor, data.gov.ro)

| Ce | Unde | Ce fișiere |
|---|---|---|
| Situații financiare 2024 | https://data.gov.ro/dataset/situatii_financiare_2024 | toate `WEB_*.txt` + `WEB_*.csv` → `date/sf2024/` |
| Situații financiare 2023 (pentru creștere) | https://data.gov.ro/dataset/situatii_financiare2023 | la fel → `date/sf2023/` |
| Date de identificare plătitori (cel mai recent set) | https://data.gov.ro/organization/mfp | BUCUREȘTI, ILFOV, PRAHOVA → `date/id/` |

## 2. Rulare

```bash
python3 build_leads.py --fin-dir date/sf2024 --fin-prev-dir date/sf2023 \
    --id-file date/id/BUCURESTI.csv --id-file date/id/ILFOV.csv \
    --id-file date/id/PRAHOVA.csv --eur-rate 4.97 --out leads.csv

python3 find_emails.py --in leads.csv --out leads_email.csv --limit 2000
```

## 3. Criteriile de filtrare și scor

Filtre obligatorii:
- județ București, Ilfov sau Prahova; firmă activă (fără cele radiate, dizolvate, în insolvență);
- cifra de afaceri ≥ 500.000 EUR (`--min-ca-eur`);
- fără coduri CAEN 6920 (sunt concurenți), fără 64–66 (finanțe și asigurări, au cerințe speciale), fără 84/94/99 (administrație publică și ONG-uri).

Scor 0–100 (un scor mai mare înseamnă o conversie mai probabilă):

| Criteriu | Puncte | De ce contează |
|---|---|---|
| CA între 0,5 și 10M EUR | 20 | Cumpără servicii externe; firmele mai mari au de obicei un departament financiar propriu |
| 10–150 salariați | 15 | Salarizarea și HR-ul sunt complexe, deci au nevoie de outsourcing |
| Creștere CA ≥ 20% | 15 | Firma a crescut peste ce poate duce contabilul actual |
| Scădere CA ≥ 15% | 10 | Are nevoie de analiză și restructurare de costuri |
| Pierdere sau marjă netă sub 3% | 10–15 | Are nevoie de analiză a profitabilității |
| Capitaluri proprii negative | 15 | Obligații legale (art. 153^24 din Legea 31/1990), deci problema e urgentă |
| Datorii > 70% din active | 10 | Raportări către bănci, covenant-uri, cash-flow |
| Creanțe > 40% din active | 5 | Au nevoie de control al încasărilor |
| Depășește pragurile de audit | 5 | Au nevoie de raportare financiară mai riguroasă |
| Sector complex (construcții, en-gros, transport, IT, producție, HoReCa, imobiliare, sănătate) | 10 | Contabilitate grea (stocuri, TVA, taxare inversă, e-Transport) |

## 4. Email-uri și GDPR

`find_emails.py` ia adresele doar de pe site-ul firmei. Un site ghicit din
denumire este acceptat numai dacă pagina conține CUI-ul firmei. Adresele
generice (`office@`, `contact@`, `financiar@`) au prioritate.

Contactarea B2B pe adrese generice ale firmei e în general acceptată. O adresă
nominală (`ion.popescu@firma.ro`) este însă dată personală după GDPR. De aceea:
- menționează sursa datelor și interesul legitim în primul mesaj;
- oferă dezabonare într-un singur clic și respectă imediat opoziția;
- nu trimite în masă din domeniul principal: folosește un subdomeniu dedicat, încălzit treptat.
