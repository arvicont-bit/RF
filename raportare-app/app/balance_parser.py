"""
Parser balante brute (.xlsx/.xls -> lista de linii normalizate).

Suporta detectare automata de coloane pentru cele mai intalnite formate
de export folosite pana acum (balante Dial/SARCOM/Toto):
  - format "SAGA-like": CONT / NUME / S1D / S1C / SID / SIC / DL / CL / DT / CT / SD / SC
  - format "Trial Balance" deja structurat: Cont / Debit(SI) / Credit(SI) / Debit(luna) / ...

Daca antetul nu poate fi recunoscut automat, se raporteaza eroare clara cu
coloanele gasite, ca sa poata fi mapate manual (extensie viitoare).
"""
import openpyxl
import io

# sinonime posibile pentru fiecare camp (lowercase, fara diacritice, spatii normalizate)
SYNONYMS = {
    'cont': ['cont', 'cont1', 'simbol cont', 'simbol'],
    'denumire': ['denumire', 'nume', 'nume cont', 'denumire cont', 'descriere'],
    'si_debit': ['s1d', 'sid an', 'sold initial debit', 'sold initial an debit', 'sid',
                 'sold initial debitor'],
    'si_credit': ['s1c', 'sic an', 'sold initial credit', 'sold initial an credit', 'sic',
                  'sold initial creditor'],
    'rulaj_luna_debit': ['dl', 'rulaj luna debit', 'debit luna', 'rulaj debitor curent'],
    'rulaj_luna_credit': ['cl', 'rulaj luna credit', 'credit luna', 'rulaj creditor curent'],
    'rulaj_cumulat_debit': ['dt', 'rulaj cumulat debit', 'debit cumulat', 'total debit',
                            'total sume debitoare'],
    'rulaj_cumulat_credit': ['ct', 'rulaj cumulat credit', 'credit cumulat', 'total credit',
                             'total sume creditoare'],
    'sf_debit': ['sd', 'sold final debit', 'sold final debitor'],
    'sf_credit': ['sc', 'sold final credit', 'sold final creditor'],
}


def _norm(s):
    if s is None:
        return ''
    return ' '.join(str(s).strip().lower().replace('\n', ' ').split())


def detect_columns(header_row):
    mapping = {}
    normalized = [_norm(h) for h in header_row]
    for field, syns in SYNONYMS.items():
        for idx, h in enumerate(normalized):
            if h in syns:
                mapping[field] = idx
                break
    return mapping


def parse_balance_file(file_bytes: bytes, filename: str):
    """Intoarce (lines, warnings). lines = list de dict normalizate."""
    bio = io.BytesIO(file_bytes)
    wb = openpyxl.load_workbook(bio, data_only=True)
    ws = wb.active

    header_row_idx = None
    col_map = {}
    for r in range(1, min(6, ws.max_row) + 1):
        row_vals = [c.value for c in ws[r]]
        cm = detect_columns(row_vals)
        if 'cont' in cm and ('si_debit' in cm or 'rulaj_cumulat_debit' in cm or 'sf_debit' in cm):
            header_row_idx = r
            col_map = cm
            break

    if header_row_idx is None:
        found_headers = [c.value for c in ws[1]]
        raise ValueError(
            f"Nu am putut detecta automat coloanele balantei in '{filename}'. "
            f"Antet gasit pe primul rand: {found_headers}"
        )

    def cell(row, field):
        idx = col_map.get(field)
        if idx is None:
            return 0
        v = row[idx].value
        return v if isinstance(v, (int, float)) else 0

    lines = []
    warnings = []
    for r in range(header_row_idx + 1, ws.max_row + 1):
        row = ws[r]
        cont_idx = col_map.get('cont')
        cont_val = row[cont_idx].value if cont_idx is not None else None
        if cont_val is None or str(cont_val).strip() == '':
            continue
        denumire_idx = col_map.get('denumire')
        denumire = row[denumire_idx].value if denumire_idx is not None else ''

        lines.append(dict(
            cont=str(cont_val).strip(),
            denumire=denumire,
            si_debit=cell(row, 'si_debit'),
            si_credit=cell(row, 'si_credit'),
            rulaj_luna_debit=cell(row, 'rulaj_luna_debit'),
            rulaj_luna_credit=cell(row, 'rulaj_luna_credit'),
            rulaj_cumulat_debit=cell(row, 'rulaj_cumulat_debit'),
            rulaj_cumulat_credit=cell(row, 'rulaj_cumulat_credit'),
            sf_debit=cell(row, 'sf_debit'),
            sf_credit=cell(row, 'sf_credit'),
        ))

    if not lines:
        warnings.append('Nicio linie de balanta gasita dupa header.')

    return lines, warnings
